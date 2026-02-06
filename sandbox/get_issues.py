import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from github import Auth, Github

SCRIPT_DIR = Path(__file__).parent
CREDENTIAL_HELPER = SCRIPT_DIR / "git-credential-app.py"
BIN_DIR = str(SCRIPT_DIR / "bin")
POLL_INTERVAL = 15

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

def claim_issue(issue):
    """Add the 'claimed' label to an issue."""
    issue.add_to_labels("claimed")
    print(f"Added 'claimed' label to issue #{issue.number}")

def parse_and_display_stream_line(line):
    """Parse a JSON stream line and display relevant information."""
    try:
        data = json.loads(line)

        # Handle TODO tool usage
        if data.get("type") == "user" and "tool_use_result" in data:
            result = data["tool_use_result"]
            if "newTodos" in result:
                new_todos = result["newTodos"]
                if new_todos:
                    print("\n📋 Todo List Updated:")
                    for todo in new_todos:
                        status_icon = {
                            "in_progress": "🔄",
                            "completed": "✅",
                            "pending": "⏳"
                        }.get(todo["status"], "•")
                        print(f"  {status_icon} {todo['content']} ({todo['status']})")
                    print()

        # Handle assistant text messages (but filter out tool-related ones)
        elif data.get("type") == "assistant":
            message = data.get("message", {})
            content = message.get("content", [])
            for item in content:
                if item.get("type") == "text":
                    text = item.get("text", "").strip()
                    # Only print if it's not empty
                    if text:
                        print(f"💬 {text}")

    except json.JSONDecodeError:
        # If it's not valid JSON, just pass it through
        pass

def process_issue(issue):
    """Clone the repo, run Claude Code on the issue, return True on success."""
    token = get_token()
    print(f"Working on #{issue.number}: {issue.title}")

    # Claim the issue by adding the 'claimed' label
    claim_issue(issue)

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
          if issue.pull_request is None:
            prompt = (
              f"Make a pull request resolving issue #{issue.number}.\n\n" +
              "If appropriate, test your changes in marcia-pedals/clever-computer-test by: " +
              "(1) using gh to insert test issues/prs/reviews/etc into the repo and (2) running get_issues.py " +
              "with --repo marcia-pedals/clever-computer-test --test-prompt and --token-path $HOME/.github-app-token\n\n" +
              "If you can't accomplish the task or can't test your work, add a comment to the issue explaining instead of making a PR.\n\n" +
              "If you do succeed, also add a comment to the issue explaining what you did any any issues you ran into along the way."
            )
          else:
            prompt = (
              f"Update #{issue.number} to address the latest review.\n\n" +
              "If appropriate, test your changes in marcia-pedals/clever-computer-test by: " +
              "(1) using gh to insert test issues/prs/reviews/etc into the repo and (2) running get_issues.py " +
              "with --repo marcia-pedals/clever-computer-test --test-prompt and --token-path $HOME/.github-app-token\n\n" +
              "If you can't accomplish the task or can't test your work, add a comment to the PR explaining why.\n\n" +
              "If you do succeed, also add a comment to the PR explaining what you did any any issues you ran into along the way."
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

        for line in proc.stdout:
            parse_and_display_stream_line(line)

        proc.wait()

        if proc.returncode == 0:
            print(f"\n✅ Successfully processed issue #{issue.number}")
        else:
            print(f"\n❌ Failed to process issue #{issue.number} (exit code: {proc.returncode})")


def _pr_has_unaddressed_review_comments(repo, pr_number):
    """Return True if the PR has at least one reviewer whose latest review requests changes."""
    pr = repo.get_pull(pr_number)
    latest_by_author = {}
    for review in pr.get_reviews():
        if review.state in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest_by_author[review.user.login] = review.state
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
    print("Starting issue polling loop...")
    while True:
        issue = get_unprocessed_issue()
        if issue is None:
            print(f"No unprocessed issues. Waiting {POLL_INTERVAL}s...")
            time.sleep(POLL_INTERVAL)
            continue

        process_issue(issue)

        print(f"Waiting {POLL_INTERVAL} seconds before checking for new issues...")
        time.sleep(POLL_INTERVAL)
else:
    issue = get_unprocessed_issue()
    if issue is None:
        print("No unprocessed open issues found.")
    else:
        process_issue(issue)
