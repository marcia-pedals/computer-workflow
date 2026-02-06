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
sudo cp $HOME/computer-workflow/sandbox-nix.conf /etc/nix/nix.conf
sudo launchctl kickstart -k system/systems.determinate.nix-daemon 2>/dev/null \
  || sudo launchctl kickstart -k system/org.nixos.nix-daemon 2>/dev/null \
  || true

# --- Install Claude Code ---
source "$HOME/.zprofile"
npm install -g @anthropic-ai/claude-code

sync
