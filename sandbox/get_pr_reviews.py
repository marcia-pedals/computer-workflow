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
BOT_LOGIN = "clever-computer[bot]"

token = TOKEN_PATH.read_text().strip()
g = Github(auth=Auth.Token(token))

repo = g.get_repo(REPO)
# Track which PR reviews we've already processed
# Key: PR number, Value: set of review IDs we've processed
processed_reviews = {}

print("Starting PR review polling loop...")

while True:
    # Refresh token in case it has been updated
    token = TOKEN_PATH.read_text().strip()
    g = Github(auth=Auth.Token(token))
    repo = g.get_repo(REPO)

    # Get all open PRs created by the bot
    pulls = list(repo.get_pulls(state="open"))
    bot_prs = [pr for pr in pulls if pr.user.login == BOT_LOGIN]

    if not bot_prs:
        print("No open PRs created by bot found. Waiting for PRs...")
        time.sleep(POLL_INTERVAL)
        continue

    # Check each PR for new reviews
    pr_with_new_review = None
    new_reviews = []

    for pr in bot_prs:
        pr_number = pr.number

        # Initialize tracking for this PR if needed
        if pr_number not in processed_reviews:
            processed_reviews[pr_number] = set()

        # Get all reviews for this PR
        reviews = list(pr.get_reviews())

        # Filter out reviews we've already processed and reviews by the bot itself
        unprocessed_reviews = [
            review for review in reviews
            if review.id not in processed_reviews[pr_number]
            and review.user.login != BOT_LOGIN
        ]

        if unprocessed_reviews:
            pr_with_new_review = pr
            new_reviews = unprocessed_reviews
            break

    if not pr_with_new_review:
        print(f"Checked {len(bot_prs)} bot PR(s), no new reviews. Waiting...")
        time.sleep(POLL_INTERVAL)
        continue

    # Process the PR with new reviews
    pr = pr_with_new_review
    print(f"Found {len(new_reviews)} new review(s) on PR #{pr.number}: {pr.title}")

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

        # Checkout the PR branch
        subprocess.run(
            ["git", "checkout", pr.head.ref],
            cwd=tmpdir,
            check=True,
        )

        # Build the prompt with review feedback
        review_details = []
        for review in new_reviews:
            review_info = f"Review by {review.user.login} ({review.state}):\n{review.body or '(no comment)'}"

            # Get review comments (inline comments on specific lines)
            review_comments = list(pr.get_review_comments())
            relevant_comments = [c for c in review_comments if c.pull_request_review_id == review.id]

            if relevant_comments:
                review_info += "\n\nInline comments:"
                for comment in relevant_comments:
                    review_info += f"\n- {comment.path}:{comment.line}: {comment.body}"

            review_details.append(review_info)

        reviews_text = "\n\n---\n\n".join(review_details)

        prompt = (
            f"There is a GitHub pull request #{pr.number}: \"{pr.title}\"\n\n"
            f"PR Description:\n{pr.body or '(no description)'}\n\n"
            f"This PR has received the following review(s):\n\n{reviews_text}\n\n"
            f"Please address the review feedback by making the necessary changes to the code. "
            f"You are currently on the branch '{pr.head.ref}'. Make your changes, commit them, "
            f"and push to update the PR."
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

        # Mark these reviews as processed regardless of success/failure
        for review in new_reviews:
            processed_reviews[pr.number].add(review.id)

        if proc.returncode == 0:
            print(f"Successfully processed reviews for PR #{pr.number}")
        else:
            print(f"Failed to process reviews for PR #{pr.number} (exit code: {proc.returncode})")

    print(f"Waiting {POLL_INTERVAL} seconds before checking for new reviews...")
    time.sleep(POLL_INTERVAL)
