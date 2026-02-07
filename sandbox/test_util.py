#!/usr/bin/env python3
"""Shared utilities for integration tests."""

import subprocess
import sys
import time
from pathlib import Path

from github import Auth, Github
from github.Issue import Issue
from github.PullRequest import PullRequest
from github.Repository import Repository

# Test configuration - hardcoded for marcia-pedals/clever-computer-test
REPO = "marcia-pedals/clever-computer-test"
TOKEN_PATH = Path("/Users/admin/.github-app-token")

SCRIPT_DIR = Path(__file__).parent


def get_github_client() -> tuple[Github, Repository]:
    """Get authenticated GitHub client and repository."""
    token = TOKEN_PATH.read_text().strip()
    g = Github(auth=Auth.Token(token))
    repo = g.get_repo(REPO)
    return g, repo


def run_get_issues_py(issue_number: int) -> bool:
    """Run get_issues.py with --test-prompt and --process-issue for the given issue number."""
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "get_issues.py"),
        "--repo", REPO,
        "--token-path", str(TOKEN_PATH),
        "--test-prompt",
        "--process-issue", str(issue_number),
    ]
    print(f"\n▶ Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode != 0:
        print(f"❌ get_issues.py failed with exit code {result.returncode}")
        return False
    return True


def verify_claimed(issue: Issue, should_be_claimed: bool = True) -> None:
    """Verify if an issue has the 'claimed' label."""
    issue.update()  # Refresh issue state
    is_claimed = any(label.name == "claimed" for label in issue.labels)
    if should_be_claimed:
        assert is_claimed, f"Issue #{issue.number} should be claimed but isn't"
        print(f"✓ Issue #{issue.number} is claimed")
    else:
        assert not is_claimed, f"Issue #{issue.number} should not be claimed but is"
        print(f"✓ Issue #{issue.number} is not claimed")


def verify_pr_exists(repo: Repository, issue: Issue, max_wait: int = 30) -> PullRequest:
    """Verify that a PR was created for the issue.

    Args:
        repo: The GitHub repository
        issue: The issue to check for an associated PR
        max_wait: Maximum seconds to wait for PR to appear (default 30)
    """
    # Poll for PR creation, as it may take a few seconds for the gh CLI to finish
    print(f"  Waiting for PR to be created for issue #{issue.number}...")
    start_time = time.time()

    while time.time() - start_time < max_wait:
        prs = list(repo.get_pulls(state="open", sort="created", direction="desc"))
        for pr in prs:
            # Check body and title for references to the issue
            body = pr.body or ""
            title = pr.title or ""
            if (f"#{issue.number}" in body or
                f"issue #{issue.number}" in body.lower() or
                f"#{issue.number}" in title or
                f"issue-{issue.number}" in pr.head.ref):
                print(f"✓ PR #{pr.number} was created for issue #{issue.number}")
                return pr

        # Wait a bit before checking again
        time.sleep(2)

    # One final check with more verbose output
    print(f"  ⚠ Could not find PR after {max_wait}s. Checking all recent PRs:")
    prs = list(repo.get_pulls(state="open", sort="created", direction="desc"))[:5]
    for pr in prs:
        print(f"    PR #{pr.number}: {pr.title}, branch: {pr.head.ref}")

    raise AssertionError(f"No PR found for issue #{issue.number} after waiting {max_wait}s")


def verify_review_dismissed(repo: Repository, pr: PullRequest) -> None:
    """Verify that CHANGES_REQUESTED reviews were dismissed."""
    pr_obj = repo.get_pull(pr.number)
    reviews = list(pr_obj.get_reviews())
    for review in reviews:
        if review.state == "CHANGES_REQUESTED":
            raise AssertionError(f"PR #{pr.number} still has an active CHANGES_REQUESTED review")
    print(f"✓ All CHANGES_REQUESTED reviews on PR #{pr.number} have been dismissed")


def cleanup_issue(repo: Repository, issue: Issue) -> None:
    """Close an issue."""
    try:
        issue.edit(state="closed")
        print(f"✓ Closed issue #{issue.number}")
    except Exception as e:
        print(f"⚠ Could not close issue #{issue.number}: {e}")


def cleanup_pr(repo: Repository, pr: PullRequest) -> None:
    """Close a PR and delete its branch."""
    try:
        pr_obj = repo.get_pull(pr.number)
        pr_obj.edit(state="closed")
        print(f"✓ Closed PR #{pr.number}")

        # Delete the branch
        try:
            ref = repo.get_git_ref(f"heads/{pr.head.ref}")
            ref.delete()
            print(f"✓ Deleted branch {pr.head.ref}")
        except Exception as e:
            print(f"⚠ Could not delete branch {pr.head.ref}: {e}")
    except Exception as e:
        print(f"⚠ Could not close PR #{pr.number}: {e}")
