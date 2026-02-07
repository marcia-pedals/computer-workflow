#!/usr/bin/env python3
"""Test: Changes requested -> claims PR, updates PR, unclaims PR, dismisses review."""

from typing import Optional

from github.Issue import Issue
from github.PullRequest import PullRequest

from test_util import (
    cleanup_issue,
    cleanup_pr,
    get_github_client,
    run_get_issues_py,
    verify_claimed,
    verify_pr_exists,
    verify_review_dismissed,
)


def test_changes_requested() -> None:
    """Test: Changes requested -> claims PR, updates PR, unclaims PR, dismisses review."""
    print("\n" + "="*60)
    print("TEST: Changes Requested Flow")
    print("="*60)

    _, repo = get_github_client()
    issue: Optional[Issue] = None
    pr: Optional[PullRequest] = None

    try:
        # First create an issue and PR for it
        issue = repo.create_issue(
            title="Test issue for changes requested test",
            body="This is a test issue for the changes requested flow."
        )
        print(f"✓ Created test issue #{issue.number}")

        # Process the issue to create a PR
        success = run_get_issues_py(issue.number)
        assert success, "get_issues.py failed to create PR"

        # Get the created PR
        pr = verify_pr_exists(repo, issue)
        pr_issue = repo.get_issue(pr.number)

        # Create a review requesting changes
        pr_obj = repo.get_pull(pr.number)
        _review = pr_obj.create_review(
            body="Please make some changes for testing purposes.",
            event="REQUEST_CHANGES"
        )
        print(f"✓ Created CHANGES_REQUESTED review on PR #{pr.number}")

        # Process the PR
        success = run_get_issues_py(pr.number)
        assert success, "get_issues.py failed to process changes requested"

        # Verify the PR was claimed during processing (we can't check this in real-time,
        # but we can verify it was unclaimed afterwards)
        verify_claimed(pr_issue, should_be_claimed=False)

        # Verify the review was dismissed
        verify_review_dismissed(repo, pr)

        print("\n✅ TEST PASSED: Changes Requested Flow")

    finally:
        # Cleanup
        print("\n" + "="*60)
        print("CLEANUP")
        print("="*60)
        if pr:
            cleanup_pr(repo, pr)
        if issue:
            cleanup_issue(repo, issue)


if __name__ == "__main__":
    test_changes_requested()
