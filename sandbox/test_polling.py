#!/usr/bin/env python3
"""Integration test for the polling functionality.

WARNING: This test closes all issues and PRs in the repo before running.
DO NOT run this in parallel with other tests or production use.

Tests the polling loop:
1. Closes all existing issues and PRs
2. Creates sample issues
3. Runs the polling loop with --poll-until-no-work
4. Verifies all issues are claimed and have PRs created
"""

import subprocess
import sys
import time
from pathlib import Path

from github.Issue import Issue

from test_util import REPO, TOKEN_PATH, get_github_client

SCRIPT_DIR = Path(__file__).parent

# Default timeout for polling (10 minutes)
DEFAULT_TIMEOUT = 600


def close_all_issues_and_prs() -> int:
    """Close all open issues and PRs in the repo."""
    _, repo = get_github_client()
    print("\n▶ Closing all open issues and PRs...")
    issues = list(repo.get_issues(state="open"))
    closed_count = 0
    for issue in issues:
        issue.edit(state="closed")
        closed_count += 1
        print(f"  ✓ Closed #{issue.number}: {issue.title}")

    print(f"✓ Closed {closed_count} issues/PRs")
    return closed_count


def create_test_issues() -> list[Issue]:
    """Create sample test issues."""
    _, repo = get_github_client()
    print("\n▶ Creating test issues...")
    issues = []

    issue1 = repo.create_issue(
        title="Polling test issue 1",
        body="This is the first test issue for polling."
    )
    issues.append(issue1)
    print(f"  ✓ Created issue #{issue1.number}")

    issue2 = repo.create_issue(
        title="Polling test issue 2",
        body="This is the second test issue for polling."
    )
    issues.append(issue2)
    print(f"  ✓ Created issue #{issue2.number}")

    issue3 = repo.create_issue(
        title="Polling test issue 3",
        body="This is the third test issue for polling."
    )
    issues.append(issue3)
    print(f"  ✓ Created issue #{issue3.number}")

    print(f"✓ Created {len(issues)} test issues")
    return issues


def run_polling_loop_until_no_work(timeout: int = DEFAULT_TIMEOUT) -> tuple[str, int]:
    """Run get_issues.py in polling mode until no work is left.

    Args:
        timeout: Maximum time to run in seconds (default 600 = 10 minutes)

    Returns:
        Tuple of (output, returncode)
    """
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "get_issues.py"),
        "--repo", REPO,
        "--token-path", str(TOKEN_PATH),
        "--test-prompt",
        "--poll",
        "--poll-until-no-work",
    ]
    print(f"\n▶ Starting polling loop with --poll-until-no-work (timeout: {timeout}s)...")
    print(f"  Command: {' '.join(cmd)}")

    start_time = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    try:
        # Wait for the process to complete or timeout
        output, _ = proc.communicate(timeout=timeout)
        elapsed = int(time.time() - start_time)
        print(f"\n✓ Polling loop completed in {elapsed} seconds")

        # Print captured output
        if output:
            print("\n" + "="*60)
            print("POLLING OUTPUT")
            print("="*60)
            print(output)

        returncode = proc.returncode or 0
        return output or "", returncode

    except subprocess.TimeoutExpired:
        print(f"\n❌ Polling loop timed out after {timeout} seconds!")
        proc.kill()
        output, _ = proc.communicate()

        # Print captured output even on timeout
        if output:
            print("\n" + "="*60)
            print("POLLING OUTPUT (before timeout)")
            print("="*60)
            print(output)

        raise AssertionError(f"Polling loop did not complete within {timeout} seconds")


def verify_all_issues_processed(issues: list[Issue]) -> None:
    """Verify that all issues were claimed and have PRs created."""
    _, repo = get_github_client()
    print("\n▶ Verifying all issues were processed...")

    claimed_issues = []
    issues_with_prs = []

    for issue in issues:
        issue.update()  # Refresh state
        is_claimed = any(label.name == "claimed" for label in issue.labels)
        if is_claimed:
            claimed_issues.append(issue.number)
            print(f"  ✓ Issue #{issue.number} is claimed")
        else:
            print(f"  ❌ Issue #{issue.number} is NOT claimed")

    # Check for created PRs
    prs = list(repo.get_pulls(state="open"))
    for issue in issues:
        found_pr = False
        for pr in prs:
            body = pr.body or ""
            if (f"#{issue.number}" in body or
                f"issue #{issue.number}" in body.lower() or
                f"issue-{issue.number}" in pr.head.ref):
                found_pr = True
                issues_with_prs.append(issue.number)
                print(f"  ✓ PR #{pr.number} was created for issue #{issue.number}")
                break

        if not found_pr:
            print(f"  ❌ No PR found for issue #{issue.number}")

    print(f"\n✓ Summary: {len(claimed_issues)}/{len(issues)} issues claimed, "
          f"{len(issues_with_prs)}/{len(issues)} issues have PRs")

    # Assert all issues were processed
    assert len(claimed_issues) == len(issues), \
        f"Expected all {len(issues)} issues to be claimed, but only {len(claimed_issues)} were"
    assert len(issues_with_prs) == len(issues), \
        f"Expected all {len(issues)} issues to have PRs, but only {len(issues_with_prs)} do"


def test_polling() -> None:
    """Run the polling integration test."""
    print("="*60)
    print("POLLING INTEGRATION TEST")
    print("="*60)
    print(f"Testing repository: {REPO}")
    print(f"Token path: {TOKEN_PATH}")
    print(f"Timeout: {DEFAULT_TIMEOUT} seconds")
    print("="*60)
    print("\n⚠ WARNING: This test will close ALL open issues and PRs!")
    print("⚠ DO NOT run in parallel with other tests or production use!")
    print("\nPress Ctrl+C within 5 seconds to cancel...")

    try:
        time.sleep(5)
    except KeyboardInterrupt:
        print("\n❌ Cancelled by user")
        sys.exit(1)

    # Step 1: Close all existing issues and PRs
    close_all_issues_and_prs()

    # Step 2: Create test issues
    issues = create_test_issues()

    # Step 3: Run the polling loop
    _output, returncode = run_polling_loop_until_no_work(timeout=DEFAULT_TIMEOUT)

    if returncode != 0:
        raise AssertionError(f"Polling loop exited with code {returncode}")

    # Step 4: Verify all issues were processed
    verify_all_issues_processed(issues)

    # Print summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print("✅ PASSED: All issues were claimed and have PRs")


if __name__ == "__main__":
    test_polling()
