import argparse
import json
import os
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from pathlib import Path
from typing import Any, Literal
from github import Auth, Github
from github.Issue import Issue
from github.Repository import Repository

SCRIPT_DIR: Path = Path(__file__).parent
CREDENTIAL_HELPER: Path = SCRIPT_DIR / "git-credential-app.py"
BIN_DIR: str = str(SCRIPT_DIR / "bin")
POLL_INTERVAL: int = 15
MAX_WORKERS: int = 5

# Template for test instructions appended to prompts
TEST_INSTRUCTIONS: str = (
    "\n\nIf appropriate, test your changes in marcia-pedals/clever-computer-test by running: "
    "cd sandbox && python3 test_issue_to_pr.py && python3 test_changes_requested.py && python3 test_merge_conflict.py"
    "\n\nRemember to update the integration tests if you add new functionality."
    "\n\nFor Python changes: Run pyright"
)

APP_ID: int = 2810181
INSTALLATION_ID: int = 108446080

parser: argparse.ArgumentParser = argparse.ArgumentParser(description="Poll GitHub issues and process them with Claude")
parser.add_argument("--repo", required=True, help="Target GitHub repo (owner/name)")
parser.add_argument("--poll", action="store_true", help="Poll continuously for new issues instead of processing one and exiting")
parser.add_argument("--poll-until-no-work", action="store_true", help="Exit when there is no work left (used with --poll)")
parser.add_argument("--test-prompt", action="store_true", help="Use a simplified prompt for faster testing")
parser.add_argument("--process-issue", type=int, metavar="ISSUE_NUMBER", help="Process a specific issue number instead of finding the next unprocessed one")
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument("--token-path", help="Path to a file containing a GitHub token")
group.add_argument("--secret-key-path", help="Path to the GitHub App private key PEM file")
args: argparse.Namespace = parser.parse_args()

REPO: str = args.repo

token_path: Path
app_auth: Auth.AppInstallationAuth | None = None

if args.token_path:
    token_path = Path(args.token_path)
else:
    # Generate token from app key; write to a temp file for gh-wrapper
    fd, temp_path = tempfile.mkstemp(suffix=".token")
    import os as _os
    _os.close(fd)
    token_path = Path(temp_path)
    key: str = Path(args.secret_key_path).read_text()
    app_auth = Auth.AppInstallationAuth(Auth.AppAuth(APP_ID, key), INSTALLATION_ID)


def get_token() -> str:
    """Return a fresh token, updating the token file if in secret-key mode."""
    if args.token_path:
        return token_path.read_text().strip()
    assert app_auth is not None
    tok: str = Github(auth=app_auth).requester.auth.token  # type: ignore[assignment]
    token_path.write_text(tok)
    return tok


token: str = get_token()
g: Github = Github(auth=Auth.Token(token))

repo: Repository = g.get_repo(REPO)

def claim_issue(issue: Issue, task_num: int | None = None) -> None:
    """Add the 'claimed' label to an issue."""
    issue.add_to_labels("claimed")
    prefix: str = f"[{task_num}] " if task_num is not None else ""
    print(f"{prefix}Added 'claimed' label to issue #{issue.number}")

def unclaim_issue(issue: Issue, task_num: int | None = None) -> None:
    """Remove the 'claimed' label from a PR (not a regular issue)."""
    if issue.pull_request is None:
        return  # Only unclaim PRs, not regular issues
    issue.remove_from_labels("claimed")
    prefix: str = f"[{task_num}] " if task_num is not None else ""
    print(f"{prefix}Removed 'claimed' label from PR #{issue.number}")

def re_request_reviews(issue: Issue, task_num: int | None = None) -> None:
    """Dismiss CHANGES_REQUESTED reviews and re-request reviews from all reviewers."""
    if issue.pull_request is None:
        return  # Not a PR, nothing to do

    pr = repo.get_pull(issue.number)
    reviewers: set[str] = set()

    # Dismiss CHANGES_REQUESTED reviews so the PR isn't picked up again,
    # and collect reviewers to re-request.
    for review in pr.get_reviews():
        if review.user.login == pr.user.login:
            continue
        reviewers.add(review.user.login)
        if review.state == "CHANGES_REQUESTED":
            review.dismiss("Changes have been addressed.")

    prefix: str = f"[{task_num}] " if task_num is not None else ""
    if reviewers:
        pr.create_review_request(reviewers=list(reviewers))
        print(f"{prefix}Dismissed stale reviews and re-requested reviews from {', '.join(reviewers)} on PR #{issue.number}")

def parse_and_display_stream_line(line: str, task_num: int | None = None, output_buffer: list[str] | None = None) -> None:
    """Parse a JSON stream line and display relevant information."""
    prefix: str = f"[{task_num}] " if task_num is not None else ""
    try:
        data: dict[str, Any] = json.loads(line)

        # Handle TODO tool usage
        if data.get("type") == "user" and "tool_use_result" in data:
            result: Any = data["tool_use_result"]
            if "newTodos" in result:
                new_todos: Any = result["newTodos"]
                if new_todos:
                    msg: str = f"\n{prefix}📋 Todo List Updated:"
                    print(msg)
                    if output_buffer is not None:
                        output_buffer.append(msg)
                    for todo in new_todos:
                        status_icon: str = {
                            "in_progress": "🔄",
                            "completed": "✅",
                            "pending": "⏳"
                        }.get(todo["status"], "•")
                        todo_msg: str = f"{prefix}  {status_icon} {todo['content']} ({todo['status']})"
                        print(todo_msg)
                        if output_buffer is not None:
                            output_buffer.append(todo_msg)
                    print()
                    if output_buffer is not None:
                        output_buffer.append("")

        # Handle assistant text messages (but filter out tool-related ones)
        elif data.get("type") == "assistant":
            message: dict[str, Any] = data.get("message", {})
            content: list[Any] = message.get("content", [])
            for item in content:
                if item.get("type") == "text":
                    text: str = item.get("text", "").strip()
                    # Only print if it's not empty
                    if text:
                        msg = f"{prefix}💬 {text}"
                        print(msg)
                        if output_buffer is not None:
                            output_buffer.append(msg)

    except json.JSONDecodeError:
        # If it's not valid JSON, just pass it through
        pass

def process_issue(issue: Issue, reason: Literal["issue", "review_comments", "merge_conflict"] = "issue", task_num: int | None = None) -> None:
    """Clone the repo, run Claude Code on the issue, return True on success.

    Args:
        issue: The GitHub issue or PR to process
        reason: One of "issue", "review_comments", or "merge_conflict"
        task_num: Optional task number for logging in parallel mode
    """
    token: str = get_token()
    prefix: str = f"[{task_num}] " if task_num is not None else ""
    print(f"{prefix}Working on #{issue.number}: {issue.title}")

    # Claim the issue by adding the 'claimed' label
    claim_issue(issue, task_num)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Prevent git from trying GUI/interactive credential prompts
        clone_env: dict[str, str] = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

        # Clone the repo using the app token
        clone_url: str = f"https://x-access-token:{token}@github.com/{REPO}.git"
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

        # If processing a PR, checkout the PR branch
        if issue.pull_request is not None:
            pr = repo.get_pull(issue.number)
            pr_branch = pr.head.ref
            pr_repo = pr.head.repo.full_name if pr.head.repo else REPO

            # Only handle PRs from the same repo, not forks
            if pr_repo != REPO:
                raise Exception(f"PR #{issue.number} is from a fork ({pr_repo}). Fork PRs are not supported.")

            # PR is from the same repo, fetch and checkout
            subprocess.run(
                ["git", "fetch", "origin", pr_branch],
                cwd=tmpdir,
                check=True,
                env=clone_env,
            )
            subprocess.run(
                ["git", "checkout", "-b", pr_branch, f"origin/{pr_branch}"],
                cwd=tmpdir,
                check=True,
            )
            print(f"{prefix}Checked out PR branch: {pr_branch}")

        # Set token_path for use in environment variable
        token_path_str: str = os.path.expanduser("~/.github-app-token")

        prompt: str
        if args.test_prompt:
          if issue.pull_request is None:
            prompt = f"Make a dummy pull request for issue #{issue.number} for testing purposes. Keep changes minimal."
          else:
            prompt = f"Make a dummy update to PR #{issue.number} for testing purposes. Keep changes minimal."
        else:
          test_instructions: str = TEST_INSTRUCTIONS.format(token_path=token_path_str)

          if reason == "issue":
            prompt = f"Make a pull request resolving issue #{issue.number}." + test_instructions
          elif reason == "review_comments":
            prompt = f"Update #{issue.number} to address the latest review." + test_instructions
          elif reason == "merge_conflict":
            prompt = f"Resolve conflicts with base in #{issue.number}." + test_instructions
          else:
            # Fallback for unknown reason
            prompt = f"Update #{issue.number}." + test_instructions

        # Prepend bin/ to PATH so our gh wrapper is used instead of the real gh.
        # Disable interactive git prompts in case macOS keychain dialog triggers.
        env: dict[str, str] = {
            **os.environ,
            "PATH": f"{BIN_DIR}:{os.environ.get('PATH', '')}",
            "GIT_TERMINAL_PROMPT": "0",
            "CW_GITHUB_TOKEN_PATH": token_path_str,
        }

        proc: subprocess.Popen[str] = subprocess.Popen(
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

        assert proc.stdin is not None
        proc.stdin.write(prompt)
        proc.stdin.close()

        # Capture output for posting as a comment
        output_buffer: list[str] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            parse_and_display_stream_line(line, task_num, output_buffer)

        proc.wait()

        if proc.returncode == 0:
            print(f"\n{prefix}✅ Successfully processed issue #{issue.number}")

            # Post captured output as a comment
            if output_buffer:
                comment_body: str = "\n".join(output_buffer)
                issue.create_comment(comment_body)
                print(f"{prefix}Posted processing output as comment on #{issue.number}")

            # After successful processing, remove claimed label and re-request reviews
            unclaim_issue(issue, task_num)
            re_request_reviews(issue, task_num)
        else:
            print(f"\n{prefix}❌ Failed to process issue #{issue.number} (exit code: {proc.returncode})")


def _pr_has_unaddressed_review_comments(repo: Repository, pr_number: int) -> bool:
    """Return True if the PR has at least one reviewer whose latest review requests changes."""
    pr = repo.get_pull(pr_number)
    latest_by_author: dict[str, str] = {}
    for review in pr.get_reviews():
        if review.state in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest_by_author[review.user.login] = review.state
    return "CHANGES_REQUESTED" in latest_by_author.values()


def _pr_has_merge_conflicts(repo: Repository, pr_number: int) -> bool:
    """Return True if the PR has merge conflicts with its base branch."""
    pr = repo.get_pull(pr_number)
    return pr.mergeable is False


def get_unprocessed_issue() -> tuple[Issue | None, Literal["issue", "review_comments", "merge_conflict"] | None]:
    """Fetch the oldest open unclaimed issue or PR with unaddressed review comments or merge conflicts.

    Returns:
        Tuple of (issue, reason) where reason is one of:
        - "issue": Regular issue (not a PR)
        - "review_comments": PR with unaddressed review comments
        - "merge_conflict": PR with merge conflicts
        Returns (None, None) if no unprocessed issues found.
    """
    token: str = get_token()
    g: Github = Github(auth=Auth.Token(token))
    repo: Repository = g.get_repo(REPO)
    issues: list[Issue] = list(repo.get_issues(state="open"))

    if not issues:
        return None, None

    for i in reversed(issues):
        if any(label.name == "claimed" for label in i.labels):
            continue
        if i.pull_request is None:
            return i, "issue"
        if _pr_has_unaddressed_review_comments(repo, i.number):
            return i, "review_comments"
        if _pr_has_merge_conflicts(repo, i.number):
            return i, "merge_conflict"

    return None, None


if args.poll:
    if args.process_issue:
        print("Error: --poll and --process-issue cannot be used together")
        exit(1)

    poll_start_time: float = 0.0
    poll_timeout: float = 600.0  # 10 minutes

    if args.poll_until_no_work:
        print(f"Starting issue polling loop with {MAX_WORKERS} parallel workers (will exit when no work remains)...")
        poll_start_time = time.time()
    else:
        print(f"Starting issue polling loop with {MAX_WORKERS} parallel workers...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # List of 3-tuples: (future, issue_number, task_num)
        active_tasks: list[tuple[Future[None], int, int]] = []
        next_task_num: int = 0

        while True:
            # Check timeout if in poll-until-no-work mode
            if args.poll_until_no_work:
                elapsed: float = time.time() - poll_start_time
                if elapsed > poll_timeout:
                    print(f"\n❌ ERROR: Polling loop timed out after {int(elapsed)} seconds")
                    print(f"   Still had {len(active_tasks)} active tasks when timeout occurred")
                    exit(1)
            # Remove completed futures
            active_tasks = [(f, issue_num, task_num) for f, issue_num, task_num in active_tasks if not f.done()]

            # If we have capacity, try to get a new issue
            if len(active_tasks) < MAX_WORKERS:
                unprocessed_issue, unprocessed_reason = get_unprocessed_issue()
                if unprocessed_issue is not None and unprocessed_reason is not None:
                    task_num: int = next_task_num
                    next_task_num += 1
                    print(f"[{task_num}] Assigning issue #{unprocessed_issue.number} to task {task_num}")
                    future: Future[None] = executor.submit(process_issue, unprocessed_issue, unprocessed_reason, task_num)
                    active_tasks.append((future, unprocessed_issue.number, task_num))
                elif len(active_tasks) == 0:
                    # No issues and no active workers
                    if args.poll_until_no_work:
                        print("No unprocessed issues and no active workers. Exiting.")
                        break
                    else:
                        print(f"No unprocessed issues. Waiting {POLL_INTERVAL}s...")
                        time.sleep(POLL_INTERVAL)
                        continue

            # If all workers are busy, wait for at least one to complete
            if len(active_tasks) >= MAX_WORKERS:
                # Block until at least one worker is done
                futures_only: list[Future[None]] = [f for f, _, _ in active_tasks]
                completed_future: Future[None] = next(as_completed(futures_only))
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
    if args.process_issue:
        # Process a specific issue by number
        specific_issue: Issue = repo.get_issue(args.process_issue)
        # Determine the reason based on issue state
        specific_reason: Literal["issue", "review_comments", "merge_conflict"]
        if specific_issue.pull_request is None:
            specific_reason = "issue"
        elif _pr_has_unaddressed_review_comments(repo, specific_issue.number):
            specific_reason = "review_comments"
        elif _pr_has_merge_conflicts(repo, specific_issue.number):
            specific_reason = "merge_conflict"
        else:
            specific_reason = "issue"  # Default to issue for PRs without special conditions
        process_issue(specific_issue, specific_reason)
    else:
        # Find and process the next unprocessed issue
        found_issue, found_reason = get_unprocessed_issue()
        if found_issue is None:
            print("No unprocessed open issues found.")
        else:
            assert found_reason is not None
            process_issue(found_issue, found_reason)
