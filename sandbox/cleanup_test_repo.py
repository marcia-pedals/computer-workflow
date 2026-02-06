#!/usr/bin/env python3
"""
Cleanup script for the marcia-pedals/clever-computer-test repository.
Closes all open issues and pull requests to provide a fresh testing environment.
"""

import argparse
import sys
from pathlib import Path
from github import Auth, Github

def close_all_issues_and_prs(repo_name: str, token: str) -> dict:
    """
    Close all open issues and PRs in the specified repository.

    Args:
        repo_name: Repository in owner/name format
        token: GitHub API token

    Returns:
        Dictionary with counts of closed issues and PRs
    """
    g = Github(auth=Auth.Token(token))
    repo = g.get_repo(repo_name)

    closed_issues = 0
    closed_prs = 0

    # Get all open issues (includes PRs in GitHub's API)
    issues = list(repo.get_issues(state="open"))

    print(f"Found {len(issues)} open items in {repo_name}")

    for issue in issues:
        if issue.pull_request is not None:
            print(f"  Closing PR #{issue.number}: {issue.title}")
            issue.edit(state="closed")
            closed_prs += 1
        else:
            print(f"  Closing issue #{issue.number}: {issue.title}")
            issue.edit(state="closed")
            closed_issues += 1

    return {
        "issues": closed_issues,
        "prs": closed_prs,
        "total": closed_issues + closed_prs
    }

def main():
    parser = argparse.ArgumentParser(
        description="Close all open issues and PRs in a GitHub repository"
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="Target GitHub repo (owner/name)"
    )
    parser.add_argument(
        "--token-path",
        required=True,
        help="Path to a file containing a GitHub token"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List items that would be closed without actually closing them"
    )

    args = parser.parse_args()

    # Read the token from file
    token_path = Path(args.token_path)
    if not token_path.exists():
        print(f"Error: Token file not found: {token_path}", file=sys.stderr)
        sys.exit(1)

    token = token_path.read_text().strip()

    if args.dry_run:
        print(f"DRY RUN: Would close all open issues and PRs in {args.repo}")
        g = Github(auth=Auth.Token(token))
        repo = g.get_repo(args.repo)
        issues = list(repo.get_issues(state="open"))

        for issue in issues:
            item_type = "PR" if issue.pull_request else "issue"
            print(f"  Would close {item_type} #{issue.number}: {issue.title}")

        print(f"\nTotal items that would be closed: {len(issues)}")
    else:
        print(f"Closing all open issues and PRs in {args.repo}...")
        result = close_all_issues_and_prs(args.repo, token)

        print(f"\n✅ Cleanup complete!")
        print(f"   Closed {result['issues']} issue(s)")
        print(f"   Closed {result['prs']} PR(s)")
        print(f"   Total: {result['total']} item(s)")

if __name__ == "__main__":
    main()
