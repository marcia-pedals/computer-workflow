import json
import os
import subprocess
import sys
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
processed_pr_reviews = set()  # Track (pr_number, review_id) tuples

print("Starting issue and PR review polling loop...")

while True:
    # Refresh token in case it has been updated
    token = TOKEN_PATH.read_text().strip()
    g = Github(auth=Auth.Token(token))
    repo = g.get_repo(REPO)

    # Check for unprocessed issues
    issues = list(repo.get_issues(state="open"))
    unprocessed_issues = [issue for issue in issues if issue.number not in processed_issues]

    # Process the latest unprocessed issue if one exists
    if unprocessed_issues:
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
    else:
        if issues:
            print(f"All {len(issues)} open issue(s) already processed")
        else:
            print("No open issues found")

    # Check for PRs with new reviews
    print("Checking for PRs with new reviews...")

    # Get all open PRs created by the bot
    pulls = list(repo.get_pulls(state="open"))
    bot_pulls = [pr for pr in pulls if pr.user.login.endswith("[bot]")]

    if bot_pulls:
        print(f"Found {len(bot_pulls)} open PR(s) created by the bot")

        # Check each PR for new reviews
        for pr in bot_pulls:
            reviews = list(pr.get_reviews())

            # Find unprocessed reviews (excluding reviews by the bot itself)
            unprocessed_reviews = [
                review for review in reviews
                if (pr.number, review.id) not in processed_pr_reviews
                and not review.user.login.endswith("[bot]")
            ]

            if unprocessed_reviews:
                # Process the latest unprocessed review
                review = unprocessed_reviews[-1]  # Get the most recent review
                print(f"Found new review on PR #{pr.number}: {pr.title}")
                print(f"Review by {review.user.login}: {review.state}")

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

                    # Set up credential helper for future git operations
                    subprocess.run(
                        ["git", "config", "credential.helper", str(CREDENTIAL_HELPER)],
                        cwd=tmpdir,
                        check=True,
                    )
                    subprocess.run(
                        ["git", "remote", "set-url", "origin", f"https://github.com/{REPO}.git"],
                        cwd=tmpdir,
                        check=True,
                    )

                    # Checkout the PR branch
                    subprocess.run(
                        ["git", "fetch", "origin", f"pull/{pr.number}/head:{pr.head.ref}"],
                        cwd=tmpdir,
                        check=True,
                        env=clone_env,
                    )
                    subprocess.run(
                        ["git", "checkout", pr.head.ref],
                        cwd=tmpdir,
                        check=True,
                    )

                    # Build the prompt with review feedback
                    review_body = review.body or "(no comment)"
                    review_comments = list(review.get_comments())

                    prompt = (
                        f"There is a GitHub PR #{pr.number}: \"{pr.title}\"\n\n"
                        f"A review has been submitted by {review.user.login} with state: {review.state}\n\n"
                        f"Review comment:\n{review_body}\n\n"
                    )

                    if review_comments:
                        prompt += "Line-specific comments:\n"
                        for comment in review_comments:
                            prompt += f"- {comment.path}:{comment.position}: {comment.body}\n"
                        prompt += "\n"

                    prompt += (
                        f"Please address the review feedback. Make the necessary changes, "
                        f"commit them, and push to the same branch ({pr.head.ref})."
                    )

                    # Run Claude Code headless
                    env = {
                        **os.environ,
                        "PATH": f"{BIN_DIR}:{os.environ.get('PATH', '')}",
                        "GIT_TERMINAL_PROMPT": "0",
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

                    # Mark this review as processed regardless of success/failure
                    processed_pr_reviews.add((pr.number, review.id))

                    if proc.returncode == 0:
                        print(f"Successfully processed review on PR #{pr.number}")
                    else:
                        print(f"Failed to process review on PR #{pr.number} (exit code: {proc.returncode})")

                # Only process one review per polling cycle
                break
    else:
        print("No open PRs created by the bot found")

    print(f"Waiting {POLL_INTERVAL} seconds before next poll...")
    time.sleep(POLL_INTERVAL)
