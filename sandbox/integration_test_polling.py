#!/usr/bin/env python3
"""Integration test for the polling functionality.

WARNING: This test closes all issues and PRs in the repo before running.
DO NOT run this in parallel with other tests or production use.

Tests the polling loop:
1. Closes all existing issues and PRs
2. Creates sample issues
3. Runs the polling loop briefly
4. Verifies issues are being picked up and processed
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

from github import Auth, Github
from github.Issue import Issue

SCRIPT_DIR = Path(__file__).parent

parser = argparse.ArgumentParser(description="Integration test for polling functionality")
parser.add_argument("--repo", required=True, help="Target GitHub repo for testing (owner/name)")
parser.add_argument("--token-path", required=True, help="Path to a file containing a GitHub token")
parser.add_argument("--poll-duration", type=int, default=60, help="How long to run the polling test (seconds)")
args = parser.parse_args()

REPO = args.repo
token_path = Path(args.token_path)
token = token_path.read_text().strip()

g = Github(auth=Auth.Token(token))
repo = g.get_repo(REPO)


def close_all_issues_and_prs() -> int:
    """Close all open issues and PRs in the repo."""
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


def run_polling_loop(duration: int) -> tuple[str, int]:
    """Run get_issues.py in polling mode for a specified duration."""
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "get_issues.py"),
        "--repo", REPO,
        "--token-path", str(token_path),
        "--test-prompt",
        "--poll",
    ]
    print(f"\n▶ Starting polling loop for {duration} seconds...")
    print(f"  Command: {' '.join(cmd)}")

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    try:
        # Let it run for the specified duration
        start_time = time.time()
        while time.time() - start_time < duration:
            time.sleep(1)
            # Check if process has terminated
            if proc.poll() is not None:
                print("⚠ Polling process terminated early")
                break

        print(f"\n✓ Polling loop ran for {int(time.time() - start_time)} seconds")
    finally:
        # Terminate the polling process
        print("▶ Stopping polling loop...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print("⚠ Process didn't terminate gracefully, killing...")
            proc.kill()
            proc.wait()

    # Print captured output
    output, _ = proc.communicate()
    if output:
        print("\n" + "="*60)
        print("POLLING OUTPUT")
        print("="*60)
        print(output)

    returncode = proc.returncode or 0
    return output or "", returncode


def verify_issues_processed(issues: list[Issue]) -> bool:
    """Verify that at least some issues were claimed/processed."""
    print("\n▶ Verifying issues were processed...")
    claimed_count = 0
    pr_count = 0

    for issue in issues:
        issue.update()  # Refresh state
        is_claimed = any(label.name == "claimed" for label in issue.labels)
        if is_claimed:
            claimed_count += 1
            print(f"  ✓ Issue #{issue.number} is claimed")

    # Check for created PRs
    prs = list(repo.get_pulls(state="open"))
    for pr in prs:
        for issue in issues:
            if f"#{issue.number}" in pr.body or f"issue #{issue.number}" in pr.body.lower():
                pr_count += 1
                print(f"  ✓ PR #{pr.number} was created for an issue")
                break

    print(f"\n✓ Found {claimed_count} claimed issues and {pr_count} created PRs")

    # Consider it a success if at least one issue was claimed or one PR was created
    if claimed_count > 0 or pr_count > 0:
        return True
    else:
        print("⚠ No issues were claimed or PRs created")
        return False


def main():
    print("="*60)
    print("POLLING INTEGRATION TEST")
    print("="*60)
    print(f"Testing repository: {REPO}")
    print(f"Token path: {token_path}")
    print(f"Poll duration: {args.poll_duration} seconds")
    print("="*60)
    print("\n⚠ WARNING: This test will close ALL open issues and PRs!")
    print("⚠ DO NOT run in parallel with other tests or production use!")
    print("\nPress Ctrl+C within 5 seconds to cancel...")

    try:
        time.sleep(5)
    except KeyboardInterrupt:
        print("\n❌ Cancelled by user")
        sys.exit(1)

    try:
        # Step 1: Close all existing issues and PRs
        close_all_issues_and_prs()

        # Step 2: Create test issues
        issues = create_test_issues()

        # Step 3: Run the polling loop
        _output, _returncode = run_polling_loop(args.poll_duration)

        # Step 4: Verify issues were processed
        success = verify_issues_processed(issues)

        # Print summary
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        if success:
            print("✅ PASSED: Polling functionality is working")
            sys.exit(0)
        else:
            print("❌ FAILED: Polling loop did not process any issues")
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
