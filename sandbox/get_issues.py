import os
import subprocess
import tempfile
import time
from pathlib import Path
from github import Auth, Github

REPO = "marcia-pedals/computer-workflow"
TOKEN_PATH = Path.home() / ".github-app-token"
SCRIPT_DIR = Path(__file__).parent
CREDENTIAL_HELPER = SCRIPT_DIR / "git-credential-app.py"
BIN_DIR = str(SCRIPT_DIR / "bin")
POLL_INTERVAL = 60  # Poll every 60 seconds

token = TOKEN_PATH.read_text().strip()
g = Github(auth=Auth.Token(token))

repo = g.get_repo(REPO)
processed_issues = set()

print("Starting issue polling loop...")

while True:
    # Refresh token in case it has been updated
    token = TOKEN_PATH.read_text().strip()
    g = Github(auth=Auth.Token(token))
    repo = g.get_repo(REPO)

    issues = list(repo.get_issues(state="open"))

    if not issues:
        print("No open issues found. Waiting for new issues...")
        time.sleep(POLL_INTERVAL)
        continue

    # Find unprocessed issues (sorted by created date descending by default)
    unprocessed_issues = [issue for issue in issues if issue.number not in processed_issues]

    if not unprocessed_issues:
        print(f"All {len(issues)} open issue(s) already processed. Waiting for new issues...")
        time.sleep(POLL_INTERVAL)
        continue

    # Process the latest unprocessed issue
    issue = unprocessed_issues[0]
    print(f"Working on #{issue.number}: {issue.title}")

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

        # Run Claude Code headless
        prompt = (
            f"There is a GitHub issue #{issue.number}: \"{issue.title}\"\n\n"
            f"{issue.body or '(no description)'}\n\n"
            f"Please work on this issue. Create a new branch, make the changes, "
            f"push the branch, and create a pull request that closes #{issue.number}."
        )

        # Prepend bin/ to PATH so our gh wrapper is used instead of the real gh.
        # Disable interactive git prompts in case macOS keychain dialog triggers.
        env = {
            **os.environ,
            "PATH": f"{BIN_DIR}:{os.environ.get('PATH', '')}",
            "GIT_TERMINAL_PROMPT": "0",
        }

        result = subprocess.run(
            [
                "claude",
                "--print",
                "--verbose",
                "--dangerously-skip-permissions",
                "--allowedTools", "Bash", "Edit", "Write", "Read", "Glob", "Grep",
            ],
            input=prompt,
            text=True,
            cwd=tmpdir,
            env=env,
        )

        # Mark this issue as processed regardless of success/failure
        processed_issues.add(issue.number)

        if result.returncode == 0:
            print(f"Successfully processed issue #{issue.number}")
        else:
            print(f"Failed to process issue #{issue.number} (exit code: {result.returncode})")

    print(f"Waiting {POLL_INTERVAL} seconds before checking for new issues...")
    time.sleep(POLL_INTERVAL)
