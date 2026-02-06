import argparse
import json
import os
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from github import Auth, Github

SCRIPT_DIR = Path(__file__).parent
CREDENTIAL_HELPER = SCRIPT_DIR / "git-credential-app.py"
BIN_DIR = str(SCRIPT_DIR / "bin")
POLL_INTERVAL = 15
MAX_WORKERS = 5

APP_ID = 2810181
INSTALLATION_ID = 108446080

parser = argparse.ArgumentParser(description="Poll GitHub issues and process them with Claude")
parser.add_argument("--repo", required=True, help="Target GitHub repo (owner/name)")
parser.add_argument("--poll", action="store_true", help="Poll continuously for new issues instead of processing one and exiting")
parser.add_argument("--test-prompt", action="store_true", help="Use a simplified prompt for faster testing")
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument("--token-path", help="Path to a file containing a GitHub token")
group.add_argument("--secret-key-path", help="Path to the GitHub App private key PEM file")
args = parser.parse_args()

REPO = args.repo

if args.token_path:
    token_path = Path(args.token_path)
else:
    # Generate token from app key; write to a temp file for gh-wrapper
    token_path = Path(tempfile.mktemp(suffix=".token"))
    key = Path(args.secret_key_path).read_text()
    app_auth = Auth.AppInstallationAuth(Auth.AppAuth(APP_ID, key), INSTALLATION_ID)


def get_token() -> str:
    """Return a fresh token, updating the token file if in secret-key mode."""
    if args.token_path:
        return token_path.read_text().strip()
    tok = Github(auth=app_auth).requester.auth.token
    token_path.write_text(tok)
    return tok


token = get_token()
g = Github(auth=Auth.Token(token))

repo = g.get_repo(REPO)

def claim_issue(issue, task_num=None):
    """Add the 'claimed' label to an issue."""
    issue.add_to_labels("claimed")
    prefix = f"[{task_num}] " if task_num is not None else ""
    print(f"{prefix}Added 'claimed' label to issue #{issue.number}")

def unclaim_issue(issue, task_num=None):
    """Remove the 'claimed' label from a PR (not a regular issue)."""
    if issue.pull_request is None:
        return  # Only unclaim PRs, not regular issues
    issue.remove_from_labels("claimed")
    prefix = f"[{task_num}] " if task_num is not None else ""
    print(f"{prefix}Removed 'claimed' label from PR #{issue.number}")

def re_request_reviews(issue, task_num=None):
    """Dismiss CHANGES_REQUESTED reviews and re-request reviews from all reviewers."""
    if issue.pull_request is None:
        return  # Not a PR, nothing to do

    pr = repo.get_pull(issue.number)
    reviewers = set()

    # Dismiss CHANGES_REQUESTED reviews so the PR isn't picked up again,
    # and collect reviewers to re-request.
    for review in pr.get_reviews():
        if review.user.login == pr.user.login:
            continue
        reviewers.add(review.user.login)
        if review.state == "CHANGES_REQUESTED":
            review.dismiss("Changes have been addressed.")

    prefix = f"[{task_num}] " if task_num is not None else ""
    if reviewers:
        pr.create_review_request(reviewers=list(reviewers))
        print(f"{prefix}Dismissed stale reviews and re-requested reviews from {', '.join(reviewers)} on PR #{issue.number}")

def parse_and_display_stream_line(line, task_num=None, output_buffer=None):
    """Parse a JSON stream line and display relevant information."""
    prefix = f"[{task_num}] " if task_num is not None else ""
    try:
        data = json.loads(line)

        # Handle TODO tool usage
        if data.get("type") == "user" and "tool_use_result" in data:
            result = data["tool_use_result"]
            if "newTodos" in result:
                new_todos = result["newTodos"]
                if new_todos:
                    msg = f"\n{prefix}📋 Todo List Updated:"
                    print(msg)
                    if output_buffer is not None:
                        output_buffer.append(msg)
                    for todo in new_todos:
                        status_icon = {
                            "in_progress": "🔄",
                            "completed": "✅",
                            "pending": "⏳"
                        }.get(todo["status"], "•")
                        todo_msg = f"{prefix}  {status_icon} {todo['content']} ({todo['status']})"
                        print(todo_msg)
                        if output_buffer is not None:
                            output_buffer.append(todo_msg)
                    print()
                    if output_buffer is not None:
                        output_buffer.append("")

        # Handle assistant text messages (but filter out tool-related ones)
        elif data.get("type") == "assistant":
            message = data.get("message", {})
            content = message.get("content", [])
            for item in content:
                if item.get("type") == "text":
                    text = item.get("text", "").strip()
                    # Only print if it's not empty
                    if text:
                        msg = f"{prefix}💬 {text}"
                        print(msg)
                        if output_buffer is not None:
                            output_buffer.append(msg)

    except json.JSONDecodeError:
        # If it's not valid JSON, just pass it through
        pass

def process_issue(issue, task_num=None):
    """Clone the repo, run Claude Code on the issue, return True on success."""
    token = get_token()
    prefix = f"[{task_num}] " if task_num is not None else ""
    print(f"{prefix}Working on #{issue.number}: {issue.title}")

    # Claim the issue by adding the 'claimed' label
    claim_issue(issue, task_num)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Prevent git from trying GUI/interactive credential prompts
        clone_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

        # Clone the repo using the app token
        clone_url = f"https://x-access-token:{token}@github.com/{REPO}.git"
        subprocess.run(
            ["git", "clone", clone_url, tmpdir],
            check=True,
            env=clone_env,
        )

        # Set up credential helper for future git operations (push etc.)
        subprocess.run(
            ["git", "config", "credential.helper", str(CREDENTIAL_HELPER)],
            cwd=tmpdir,
            check=True,
        )
        # Replace the token URL with the plain one so the credential helper is used for pushes
        subprocess.run(
            ["git", "remote", "set-url", "origin", f"https://github.com/{REPO}.git"],
            cwd=tmpdir,
            check=True,
        )

        if args.test_prompt:
          if issue.pull_request is None:
            prompt = f"Make a dummy pull request for issue #{issue.number} for testing purposes. Keep changes minimal."
          else:
            prompt = f"Make a dummy update to PR #{issue.number} for testing purposes. Keep changes minimal."
        else:
          token_path = os.path.expanduser("~/.github-app-token")
          if issue.pull_request is None:
            prompt = (
              f"Make a pull request resolving issue #{issue.number}.\n\n" +
              "If appropriate, test your changes in marcia-pedals/clever-computer-test by: " +
              "(1) using gh to insert test issues/prs/reviews/etc into the repo and (2) running get_issues.py " +
              f"with --repo marcia-pedals/clever-computer-test --test-prompt and --token-path {token_path}"
            )
          else:
            prompt = (
              f"Update #{issue.number} to address the latest review.\n\n" +
              "If appropriate, test your changes in marcia-pedals/clever-computer-test by: " +
              "(1) using gh to insert test issues/prs/reviews/etc into the repo and (2) running get_issues.py " +
              f"with --repo marcia-pedals/clever-computer-test --test-prompt and --token-path {token_path}" +
            )

        # Prepend bin/ to PATH so our gh wrapper is used instead of the real gh.
        # Disable interactive git prompts in case macOS keychain dialog triggers.
        env = {
            **os.environ,
            "PATH": f"{BIN_DIR}:{os.environ.get('PATH', '')}",
            "GIT_TERMINAL_PROMPT": "0",
            "CW_GITHUB_TOKEN_PATH": str(token_path),
        }

        proc = subprocess.Popen(
            [
                "claude",
                "--print",
                "--dangerously-skip-permissions",
                "--output-format", "stream-json",
                "--verbose",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=tmpdir,
            env=env,
        )

        proc.stdin.write(prompt)
        proc.stdin.close()

        # Capture output for posting as a comment
        output_buffer = []
        for line in proc.stdout:
            parse_and_display_stream_line(line, task_num, output_buffer)

        proc.wait()

        if proc.returncode == 0:
            print(f"\n{prefix}✅ Successfully processed issue #{issue.number}")

            # Post captured output as a comment
            if output_buffer:
                comment_body = "\n".join(output_buffer)
                issue.create_comment(comment_body)
                print(f"{prefix}Posted processing output as comment on #{issue.number}")

            # After successful processing, remove claimed label and re-request reviews
            unclaim_issue(issue, task_num)
            re_request_reviews(issue, task_num)
        else:
            print(f"\n{prefix}❌ Failed to process issue #{issue.number} (exit code: {proc.returncode})")


def _pr_has_unaddressed_review_comments(repo, pr_number):
    """Return True if the PR has at least one reviewer whose latest review requests changes."""
    pr = repo.get_pull(pr_number)
    latest_by_author = {}
    for review in pr.get_reviews():
        if review.state in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest_by_author[review.user.login] = review.state
    print(repo, pr_number, latest_by_author)
    return "CHANGES_REQUESTED" in latest_by_author.values()


def get_unprocessed_issue():
    """Fetch the oldest open unclaimed issue or PR with unaddressed review comments, or None."""
    token = get_token()
    g = Github(auth=Auth.Token(token))
    repo = g.get_repo(REPO)
    issues = list(repo.get_issues(state="open"))

    if not issues:
        return None

    for i in reversed(issues):
        if any(label.name == "claimed" for label in i.labels):
            continue
        if i.pull_request is None:
            return i
        if _pr_has_unaddressed_review_comments(repo, i.number):
            return i

    return None


if args.poll:
    print(f"Starting issue polling loop with {MAX_WORKERS} parallel workers...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # List of 3-tuples: (future, issue_number, task_num)
        active_tasks = []
        next_task_num = 0

        while True:
            # Remove completed futures
            active_tasks = [(f, issue_num, task_num) for f, issue_num, task_num in active_tasks if not f.done()]

            # If we have capacity, try to get a new issue
            if len(active_tasks) < MAX_WORKERS:
                issue = get_unprocessed_issue()
                if issue is not None:
                    task_num = next_task_num
                    next_task_num += 1
                    print(f"[{task_num}] Assigning issue #{issue.number} to task {task_num}")
                    future = executor.submit(process_issue, issue, task_num)
                    active_tasks.append((future, issue.number, task_num))
                elif len(active_tasks) == 0:
                    # No issues and no active workers
                    print(f"No unprocessed issues. Waiting {POLL_INTERVAL}s...")
                    time.sleep(POLL_INTERVAL)
                    continue

            # If all workers are busy, wait for at least one to complete
            if len(active_tasks) >= MAX_WORKERS:
                # Block until at least one worker is done
                futures_only = [f for f, _, _ in active_tasks]
                completed_future = next(as_completed(futures_only))
                # Find the matching task
                for i, (f, issue_num, task_num) in enumerate(active_tasks):
                    if f == completed_future:
                        active_tasks.pop(i)
                        print(f"[{task_num}] Task {task_num} finished processing issue #{issue_num}")
                        break
            else:
                # Brief sleep to avoid tight loop when we have capacity but no issues
                time.sleep(1)
else:
    issue = get_unprocessed_issue()
    if issue is None:
        print("No unprocessed open issues found.")
    else:
        process_issue(issue)
