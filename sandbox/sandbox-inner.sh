#!/usr/bin/env bash
set -euxo pipefail

# --- Configure git ---
git config --global --replace-all credential.helper ""
git config --global user.name "clever-computer[bot]"
git config --global user.email "2805513+clever-computer[bot]@users.noreply.github.com"

# --- Install Nix ---
curl --proto '=https' --tlsv1.2 -sSf -L https://install.determinate.systems/nix | sh -s -- install --no-confirm
. /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh

# --- Apply nix.conf ---
sudo mkdir -p /etc/nix
sudo cp /tmp/computer-workflow/sandbox-nix.conf /etc/nix/nix.conf
sudo launchctl kickstart -k system/systems.determinate.nix-daemon 2>/dev/null \
  || sudo launchctl kickstart -k system/org.nixos.nix-daemon 2>/dev/null \
  || true

# --- Install Claude Code ---
export npm_config_prefix="$HOME/.npm-global"
export PATH="$HOME/.npm-global/bin:$PATH"
nix develop /tmp/computer-workflow#sandbox --command npm install -g @anthropic-ai/claude-code

# --- Wait for token file from host ---
for i in $(seq 1 30); do
  if [[ -s "$HOME/.github-app-token" ]]; then break; fi
  echo "Waiting for token file... ($i)"
  sleep 2
done

# --- Environment ---
export PYTHONUNBUFFERED=1

# --- Set Claude Code auth ---
export CLAUDE_CODE_OAUTH_TOKEN=$(cat ~/.claude-oauth-token)

# --- Run ---
cd /tmp/computer-workflow
nix develop .#sandbox --command bash run_all_pollers.sh
