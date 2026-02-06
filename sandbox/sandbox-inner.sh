#!/usr/bin/env bash
set -euxo pipefail

# --- Wait for token file from host ---
for i in $(seq 1 30); do
  if [[ -s "$HOME/.github-app-token" ]]; then break; fi
  echo "Waiting for token file... ($i)"
  sleep 2
done

# --- Environment ---
source "$HOME/.zprofile"
. /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh
export PYTHONUNBUFFERED=1

# --- Set Claude Code auth ---
export CLAUDE_CODE_OAUTH_TOKEN=$(cat ~/.claude-oauth-token)

# --- Run ---
cd $HOME/computer-workflow
nix develop .#sandbox --command python3 get_issues.py --repo "$TARGET_REPO" --token-path "$HOME/.github-app-token" --poll
