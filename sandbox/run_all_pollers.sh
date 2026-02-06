#!/usr/bin/env bash
set -euo pipefail

# Run both polling scripts in parallel
# Each script outputs to its own log stream

echo "Starting all polling scripts..."

# Run issue polling in the background
python3 get_issues.py 2>&1 | sed 's/^/[issues] /' &
ISSUES_PID=$!

# Run PR review polling in the background
python3 get_pr_reviews.py 2>&1 | sed 's/^/[pr-reviews] /' &
PR_REVIEWS_PID=$!

# Wait for both processes
wait $ISSUES_PID $PR_REVIEWS_PID
