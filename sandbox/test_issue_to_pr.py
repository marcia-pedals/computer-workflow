#!/usr/bin/env python3
"""Test: Issue created -> creates PR for it and claims the issue."""

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
)


def test_issue_to_pr() -> None:
    """Test: Issue created -> creates PR for it and claims the issue."""
    print("\n" + "="*60)
    print("TEST: Issue -> PR Creation")
    print("="*60)

    _, repo = get_github_client()
    issue: Optional[Issue] = None
    pr: Optional[PullRequest] = None

    try:
        # Create a test issue
        issue = repo.create_issue(
            title="Test issue for integration test",
            body="This is a test issue. Please create a dummy PR for this issue."
        )
        print(f"✓ Created test issue #{issue.number}")

        # Process the issue
        success = run_get_issues_py(issue.number)
        assert success, "get_issues.py failed"

        # Verify the issue was claimed during processing
        # (After processing, if a PR was created, the issue stays claimed;
        # the PR itself gets unclaimed after success)
        verify_claimed(issue, should_be_claimed=True)

        # Verify a PR was created
        try:
            pr = verify_pr_exists(repo, issue)

            # Verify the PR is not claimed (it should be unclaimed after successful processing)
            pr_issue = repo.get_issue(pr.number)
            verify_claimed(pr_issue, should_be_claimed=False)

            print("\n✅ TEST PASSED: Issue -> PR Creation")
        except AssertionError as e:
            # PR wasn't created - check if at least a branch was created
            print(f"\n⚠ Warning: {e}")
            print("  Checking if a branch was created instead...")

            # Look for branches that reference this issue
            branches = repo.get_branches()
            for branch in branches:
                if f"issue-{issue.number}" in branch.name or f"{issue.number}" in branch.name:
                    print(f"✓ Found branch: {branch.name}")
                    print("⚠ Partial success: Branch created but PR creation failed")
                    print("  This may indicate an issue with the gh CLI wrapper")
                    raise AssertionError("Branch created but PR creation failed") from e

            print("❌ No branch or PR found for issue")
            raise

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
    test_issue_to_pr()
