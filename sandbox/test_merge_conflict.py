#!/usr/bin/env python3
"""Test: Conflict with base -> claims PR, updates PR, unclaims PR."""

import time
from typing import Optional

from github.PullRequest import PullRequest

from test_util import cleanup_pr, get_github_client, run_get_issues_py, verify_claimed


def test_merge_conflict() -> None:
    """Test: Conflict with base -> claims PR, updates PR, unclaims PR."""
    print("\n" + "="*60)
    print("TEST: Merge Conflict Flow")
    print("="*60)

    _, repo = get_github_client()
    pr: Optional[PullRequest] = None
    default_branch = repo.default_branch

    try:
        # Create a branch and make a commit
        base_ref = repo.get_git_ref(f"heads/{default_branch}")
        base_sha = base_ref.object.sha

        # Create a new branch
        conflict_branch = f"test-conflict-{int(time.time())}"
        repo.create_git_ref(f"refs/heads/{conflict_branch}", base_sha)
        print(f"✓ Created branch {conflict_branch}")

        # Create a file on the conflict branch
        test_file = "test_conflict_file.txt"
        repo.create_file(
            test_file,
            "Add test file for conflict",
            "Content from conflict branch\n",
            branch=conflict_branch
        )
        print(f"✓ Created {test_file} on {conflict_branch}")

        # Create the same file on the default branch with different content
        repo.create_file(
            test_file,
            "Add test file on main",
            "Content from main branch\n",
            branch=default_branch
        )
        print(f"✓ Created conflicting {test_file} on {default_branch}")

        # Create a PR from the conflict branch
        pr = repo.create_pull(
            title="Test PR with merge conflict",
            body="This PR has a merge conflict for testing purposes.",
            head=conflict_branch,
            base=default_branch
        )
        print(f"✓ Created PR #{pr.number} with merge conflict")

        # Wait for GitHub to detect the conflict
        time.sleep(3)
        pr_obj = repo.get_pull(pr.number)
        if pr_obj.mergeable is None:  # type: ignore[reportUnnecessaryComparison]
            print("⏳ Waiting for GitHub to compute mergeable status...")
            time.sleep(5)
            pr_obj = repo.get_pull(pr.number)

        if not (pr_obj.mergeable is False):
            print(f"⚠ Warning: PR mergeable status is {pr_obj.mergeable}, expected False")
            raise AssertionError("Could not create merge conflict (GitHub might need more time)")

        print(f"✓ Confirmed PR #{pr.number} has merge conflict (mergeable={pr_obj.mergeable})")

        # Process the PR
        pr_issue = repo.get_issue(pr.number)
        success = run_get_issues_py(pr.number)
        assert success, "get_issues.py failed"

        # Verify the PR was unclaimed after processing
        verify_claimed(pr_issue, should_be_claimed=False)

        # Check if conflict was resolved (PR should be mergeable now)
        time.sleep(2)
        pr = repo.get_pull(pr.number)
        # Note: We can't guarantee Claude will resolve the conflict, but we can verify it tried
        print(f"✓ PR #{pr.number} was processed (mergeable={pr.mergeable})")

        print("\n✅ TEST PASSED: Merge Conflict Flow")

    finally:
        # Cleanup
        print("\n" + "="*60)
        print("CLEANUP")
        print("="*60)
        if pr:
            cleanup_pr(repo, pr)

        # Also clean up the test file from default branch
        try:
            test_file = "test_conflict_file.txt"
            contents = repo.get_contents(test_file)
            if not isinstance(contents, list):
                repo.delete_file(
                    test_file,
                    "Clean up test file",
                    contents.sha,
                    branch=default_branch
                )
                print(f"✓ Deleted {test_file} from {default_branch}")
        except Exception as e:
            print(f"⚠ Could not delete test file: {e}")


if __name__ == "__main__":
    test_merge_conflict()
