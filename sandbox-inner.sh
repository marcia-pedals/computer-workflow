#!/usr/bin/env bash
set -euxo pipefail

# --- Install Nix via Determinate Systems installer ---
curl --proto '=https' --tlsv1.2 -sSf -L https://install.determinate.systems/nix | sh -s -- install --no-confirm

# Source nix in current shell
. /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh

# --- Apply nix.conf ---
sudo mkdir -p /etc/nix
sudo cp /tmp/sandbox-nix.conf /etc/nix/nix.conf
sudo launchctl kickstart -k system/systems.determinate.nix-daemon 2>/dev/null \
  || sudo launchctl kickstart -k system/org.nixos.nix-daemon 2>/dev/null \
  || sudo systemctl restart nix-daemon 2>/dev/null \
  || true

# --- Clone and build vats5 ---
git clone --depth 1 https://github.com/marcia-pedals/vats5.git /tmp/vats5
cd /tmp/vats5

export NIXPKGS_ALLOW_UNFREE=1
nix develop --impure --max-jobs auto --command bash -c '
  set -euxo pipefail
  cd server
  cmake -B build-debug -G Ninja -DCMAKE_BUILD_TYPE=Debug
  ninja -C build-debug
  cd build-debug
  ctest --label-exclude slow --output-on-failure
'
