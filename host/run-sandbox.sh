#!/usr/bin/env bash
set -euo pipefail

# --- Prevent concurrent runs ---
LOCKDIR="/tmp/computer-workflow-sandbox.lock"
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  echo "ERROR: Another instance of run-sandbox.sh is already running (lock: $LOCKDIR)."
  echo "If this is stale, remove it with: rmdir $LOCKDIR"
  exit 1
fi

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <environment.json>"
  exit 1
fi

ENV_FILE="$1"

# --- Parse environment config ---
read_config() {
  python3 -c "
import json, sys, os
val = json.load(open(sys.argv[1]))[sys.argv[2]]
if isinstance(val, str):
    print(os.path.expanduser(val))
else:
    print(val)
" "$ENV_FILE" "$1"
}

APP_ID=$(read_config app_id)
INSTALLATION_ID=$(read_config installation_id)
PRIVATE_KEY=$(read_config app_private_key_path)
TARGET_REPO=$(read_config target_repo)

HOST_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$HOST_DIR/.." && pwd)"
SANDBOX_DIR="$REPO_DIR/sandbox"
VM_NAME="computer-workflow-sandbox"

# --- Cleanup trap: stop the VM on exit ---
cleanup() {
  echo "Cleaning up..."
  [[ -n "${REFRESH_PID:-}" ]] && kill "$REFRESH_PID" 2>/dev/null || true
  tart stop "$VM_NAME" 2>/dev/null || true
  rmdir "$LOCKDIR" 2>/dev/null || true
}
trap cleanup EXIT

# --- Start pre-built VM ---
echo "Starting VM..."
tart run "$VM_NAME" --net-softnet --no-graphics &

# --- Wait for SSH ---
echo "Waiting for VM to become reachable..."
VM_IP=""
for i in $(seq 1 60); do
  VM_IP="$(tart ip "$VM_NAME" 2>/dev/null || true)"
  if [[ -n "$VM_IP" ]]; then break; fi
  sleep 2
done

if [[ -z "$VM_IP" ]]; then
  echo "ERROR: VM did not get an IP after 120s"
  exit 1
fi

SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o PreferredAuthentications=password -o ConnectTimeout=3)
export SSHPASS=admin

# Retry helper: run an ssh/scp command with retries
ssh_retry() {
  local max_retries=5
  for i in $(seq 1 "$max_retries"); do
    if "$@" 2>/dev/null; then return 0; fi
    echo "  retry $i/$max_retries..."
    sleep 3
  done
  echo "ERROR: command failed after $max_retries retries: $*"
  exit 1
}

SSH_REACHABLE=false
for i in $(seq 1 30); do
  if sshpass -e ssh "${SSH_OPTS[@]}" "admin@$VM_IP" true 2>/dev/null; then
    SSH_REACHABLE=true
    break
  fi
  sleep 2
done

if ! $SSH_REACHABLE; then
  echo "ERROR: VM SSH not reachable after 60s"
  exit 1
fi

echo "VM is SSH-reachable."

# --- Clean previous state ---
ssh_retry sshpass -e ssh "${SSH_OPTS[@]}" "admin@$VM_IP" "rm -rf ~/computer-workflow ~/environment"

# --- Copy project files into the VM ---
echo "Copying files into VM..."
ssh_retry sshpass -e scp -r "${SSH_OPTS[@]}" "$SANDBOX_DIR" "admin@$VM_IP:computer-workflow"
ssh_retry sshpass -e scp "${SSH_OPTS[@]}" "$REPO_DIR/flake.nix" "$REPO_DIR/flake.lock" "admin@$VM_IP:computer-workflow/"

# --- Copy test environment files into the VM ---
ssh_retry sshpass -e ssh "${SSH_OPTS[@]}" "admin@$VM_IP" "mkdir -p ~/environment"
python3 -c "
import json, sys
for p in json.load(open(sys.argv[1])).get('test_environment', []):
    print(p)
" "$ENV_FILE" | while read -r filepath; do
  expanded=$(python3 -c "import os,sys; print(os.path.expanduser(sys.argv[1]))" "$filepath")
  echo "Copying test env file: $expanded"
  ssh_retry sshpass -e scp "${SSH_OPTS[@]}" "$expanded" "admin@$VM_IP:environment/"
done

# --- Push Claude Code OAuth token ---
echo "Pushing Claude Code token..."
CLAUDE_TOKEN=$(cat ~/personal-projects/.secrets/claude-sub)
ssh_retry sshpass -e ssh "${SSH_OPTS[@]}" "admin@$VM_IP" "echo '$CLAUDE_TOKEN' > ~/.claude-oauth-token"
echo "Claude token pushed."

# --- Push initial token and start refresh loop ---
python3 "$HOST_DIR/refresh-token.py" --app-id "$APP_ID" --installation-id "$INSTALLATION_ID" --continuous "$PRIVATE_KEY" "$VM_IP" &
REFRESH_PID=$!

# --- Run the inner script ---
echo "Running sandbox-inner.sh inside VM..."
ssh_retry sshpass -e ssh "${SSH_OPTS[@]}" "admin@$VM_IP" "TARGET_REPO='$TARGET_REPO' bash computer-workflow/sandbox-inner.sh"
