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
processed_issues = set()

print("Starting issue polling loop...")

while True:
    # Refresh token in case it has been updated / regenerate if using secret key
    token = get_token()
    g = Github(auth=Auth.Token(token))
    repo = g.get_repo(REPO)

    issues = list(repo.get_issues(state="open"))

    if not issues:
        print("No open issues found. Waiting for new issues...")
        time.sleep(POLL_INTERVAL)
        continue

    # Filter out issues with the "claimed" label and already processed issues
    unprocessed_issues = [
        issue for issue in issues
        if issue.number not in processed_issues
        and "claimed" not in [label.name for label in issue.labels]
    ]

    if not unprocessed_issues:
        print(f"All {len(issues)} open issue(s) already processed. Waiting for new issues...")
        time.sleep(POLL_INTERVAL)
        continue

    # Process the latest unprocessed issue
    issue = unprocessed_issues[0]
    print(f"Working on #{issue.number}: {issue.title}")

    # Add the "claimed" label to the issue
    try:
        issue.add_to_labels("claimed")
        print(f"Added 'claimed' label to issue #{issue.number}")
    except Exception as e:
        print(f"Warning: Failed to add 'claimed' label to issue #{issue.number}: {e}")

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
            "CW_GITHUB_TOKEN_PATH": str(token_path),
        }

        proc = subprocess.Popen(
            [
                "claude",
                "--print",
                "--output-format", "stream-json",
                "--verbose",
                "--dangerously-skip-permissions",
                "--allowedTools", "Bash", "Edit", "Write", "Read", "Glob", "Grep",
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
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                print(line, flush=True)
                continue
            print(json.dumps(event), flush=True)

        proc.wait()

        # Mark this issue as processed regardless of success/failure
        processed_issues.add(issue.number)

        if proc.returncode == 0:
            print(f"Successfully processed issue #{issue.number}")
        else:
            print(f"Failed to process issue #{issue.number} (exit code: {proc.returncode})")

    print(f"Waiting {POLL_INTERVAL} seconds before checking for new issues...")
    time.sleep(POLL_INTERVAL)
