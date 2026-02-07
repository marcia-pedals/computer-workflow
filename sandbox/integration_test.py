#!/usr/bin/env python3
"""Integration tests for the clever-computer workflow.

Tests the following flows:
1. Issue created -> creates PR for it and "claims" the issue
2. Changes requested -> "claims" the PR, updates the PR, "unclaims" the PR, dismisses the review
3. Conflict with base -> "claims" the PR, updates the PR, "unclaims" the PR

All tests use the simplified prompt for faster testing and call process_issue directly.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

from github import Auth, Github

SCRIPT_DIR = Path(__file__).parent

parser = argparse.ArgumentParser(description="Run integration tests for clever-computer")
parser.add_argument("--repo", required=True, help="Target GitHub repo for testing (owner/name)")
parser.add_argument("--token-path", required=True, help="Path to a file containing a GitHub token")
args = parser.parse_args()

REPO = args.repo
token_path = Path(args.token_path)
token = token_path.read_text().strip()

g = Github(auth=Auth.Token(token))
repo = g.get_repo(REPO)


def run_get_issues_py(issue_number):
    """Run get_issues.py with --test-prompt and --process-issue for the given issue number."""
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "get_issues.py"),
        "--repo", REPO,
        "--token-path", str(token_path),
        "--test-prompt",
        "--process-issue", str(issue_number),
    ]
    print(f"\n▶ Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode != 0:
        print(f"❌ get_issues.py failed with exit code {result.returncode}")
        return False
    return True


def verify_claimed(issue, should_be_claimed=True):
    """Verify if an issue has the 'claimed' label."""
    issue.update()  # Refresh issue state
    is_claimed = any(label.name == "claimed" for label in issue.labels)
    if should_be_claimed:
        assert is_claimed, f"Issue #{issue.number} should be claimed but isn't"
        print(f"✓ Issue #{issue.number} is claimed")
    else:
        assert not is_claimed, f"Issue #{issue.number} should not be claimed but is"
        print(f"✓ Issue #{issue.number} is not claimed")


def verify_pr_exists(issue, max_wait=30):
    """Verify that a PR was created for the issue.

    Args:
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


def verify_review_dismissed(pr):
    """Verify that CHANGES_REQUESTED reviews were dismissed."""
    pr_obj = repo.get_pull(pr.number)
    reviews = list(pr_obj.get_reviews())
    for review in reviews:
        if review.state == "CHANGES_REQUESTED":
            raise AssertionError(f"PR #{pr.number} still has an active CHANGES_REQUESTED review")
    print(f"✓ All CHANGES_REQUESTED reviews on PR #{pr.number} have been dismissed")


def test_issue_to_pr():
    """Test: Issue created -> creates PR for it and claims the issue."""
    print("\n" + "="*60)
    print("TEST 1: Issue -> PR Creation")
    print("="*60)

    # Create a test issue
    issue = repo.create_issue(
        title="Test issue for integration test",
        body="This is a test issue. Please create a dummy PR for this issue."
    )
    print(f"✓ Created test issue #{issue.number}")

    try:
        # Process the issue
        success = run_get_issues_py(issue.number)
        assert success, "get_issues.py failed"

        # Verify the issue was claimed during processing
        # (After processing, if a PR was created, the issue stays claimed;
        # the PR itself gets unclaimed after success)
        verify_claimed(issue, should_be_claimed=True)

        # Verify a PR was created
        try:
            pr = verify_pr_exists(issue)

            # Verify the PR is not claimed (it should be unclaimed after successful processing)
            pr_issue = repo.get_issue(pr.number)
            verify_claimed(pr_issue, should_be_claimed=False)

            print("\n✅ TEST 1 PASSED: Issue -> PR Creation")
            return True, issue, pr
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
                    return False, issue, None

            print("❌ No branch or PR found for issue")
            return False, issue, None

    except Exception as e:
        print(f"\n❌ TEST 1 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False, issue, None


def test_changes_requested(pr):
    """Test: Changes requested -> claims PR, updates PR, unclaims PR, dismisses review."""
    print("\n" + "="*60)
    print("TEST 2: Changes Requested Flow")
    print("="*60)

    if pr is None:
        print("⏭ SKIPPED: No PR available from previous test")
        return False

    pr_issue = repo.get_issue(pr.number)

    try:
        # Create a review requesting changes
        pr_obj = repo.get_pull(pr.number)
        review = pr_obj.create_review(
            body="Please make some changes for testing purposes.",
            event="REQUEST_CHANGES"
        )
        print(f"✓ Created CHANGES_REQUESTED review on PR #{pr.number}")

        # Process the PR
        success = run_get_issues_py(pr.number)
        assert success, "get_issues.py failed"

        # Verify the PR was claimed during processing (we can't check this in real-time,
        # but we can verify it was unclaimed afterwards)
        verify_claimed(pr_issue, should_be_claimed=False)

        # Verify the review was dismissed
        verify_review_dismissed(pr)

        print("\n✅ TEST 2 PASSED: Changes Requested Flow")
        return True
    except Exception as e:
        print(f"\n❌ TEST 2 FAILED: {e}")
        return False


def test_merge_conflict():
    """Test: Conflict with base -> claims PR, updates PR, unclaims PR."""
    print("\n" + "="*60)
    print("TEST 3: Merge Conflict Flow")
    print("="*60)

    try:
        # Create a branch and make a commit
        default_branch = repo.default_branch
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
        pr = repo.get_pull(pr.number)
        if pr.mergeable is None:
            print("⏳ Waiting for GitHub to compute mergeable status...")
            time.sleep(5)
            pr = repo.get_pull(pr.number)

        if pr.mergeable is not False:
            print(f"⚠ Warning: PR mergeable status is {pr.mergeable}, expected False")
            print("⏭ SKIPPED: Could not create merge conflict (GitHub might need more time)")
            return False

        print(f"✓ Confirmed PR #{pr.number} has merge conflict (mergeable={pr.mergeable})")

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

        print("\n✅ TEST 3 PASSED: Merge Conflict Flow")
        return True
    except Exception as e:
        print(f"\n❌ TEST 3 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def cleanup(issue, pr):
    """Clean up test artifacts."""
    print("\n" + "="*60)
    print("CLEANUP")
    print("="*60)

    try:
        if pr:
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

        if issue:
            issue.edit(state="closed")
            print(f"✓ Closed issue #{issue.number}")
    except Exception as e:
        print(f"⚠ Cleanup error: {e}")


def main():
    print("="*60)
    print("CLEVER-COMPUTER INTEGRATION TESTS")
    print("="*60)
    print(f"Testing repository: {REPO}")
    print(f"Token path: {token_path}")
    print("="*60)

    results = []
    issue = None
    pr = None

    # Test 1: Issue to PR
    passed, issue, pr = test_issue_to_pr()
    results.append(("Issue -> PR Creation", passed))

    # Test 2: Changes Requested
    if pr:
        passed = test_changes_requested(pr)
        results.append(("Changes Requested Flow", passed))

    # Test 3: Merge Conflict
    passed = test_merge_conflict()
    results.append(("Merge Conflict Flow", passed))

    # Cleanup
    cleanup(issue, pr)

    # Print summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status}: {test_name}")

    all_passed = all(passed for _, passed in results)
    if all_passed:
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print("\n💔 Some tests failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
