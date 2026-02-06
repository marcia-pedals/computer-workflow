#!/usr/bin/env bash
set -euo pipefail

HOST_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$HOST_DIR/.." && pwd)"
SANDBOX_DIR="$REPO_DIR/sandbox"
VM_NAME="computer-workflow-sandbox"
BASE_IMAGE="ghcr.io/cirruslabs/macos-sequoia-base:latest"

# --- Cleanup trap: stop and delete the VM on exit ---
cleanup() {
  echo "Cleaning up..."
  [[ -n "${REFRESH_PID:-}" ]] && kill "$REFRESH_PID" 2>/dev/null || true
  tart stop "$VM_NAME" 2>/dev/null || true
  tart delete "$VM_NAME" 2>/dev/null || true
}
trap cleanup EXIT

# --- Create a fresh disposable VM ---
echo "Cloning base image..."
tart delete "$VM_NAME" 2>/dev/null || true
tart clone "$BASE_IMAGE" "$VM_NAME"

# --- Start VM ---
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

SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o PubkeyAuthentication=no)
export SSHPASS=admin

for i in $(seq 1 30); do
  if sshpass -e ssh "${SSH_OPTS[@]}" "admin@$VM_IP" true 2>/dev/null; then break; fi
  sleep 2
done

echo "VM is SSH-reachable."

# --- Copy project files into the VM ---
echo "Copying files into VM..."
sshpass -e scp -r "${SSH_OPTS[@]}" "$SANDBOX_DIR" "admin@$VM_IP:/tmp/computer-workflow"
sshpass -e scp "${SSH_OPTS[@]}" "$REPO_DIR/flake.nix" "$REPO_DIR/flake.lock" "admin@$VM_IP:/tmp/computer-workflow/"

# --- Push initial token and start refresh loop ---
echo "Pushing initial token..."
TOKEN=$(cd "$HOST_DIR" && python3 -c "from github_app_token import get_token; print(get_token())")
sshpass -e ssh "${SSH_OPTS[@]}" "admin@$VM_IP" "echo '$TOKEN' > ~/.github-app-token"
echo "Token pushed."

# --- Push Claude Code OAuth token ---
echo "Pushing Claude Code token..."
CLAUDE_TOKEN=$(cat ~/personal-projects/.secrets/claude-sub)
sshpass -e ssh "${SSH_OPTS[@]}" "admin@$VM_IP" "echo '$CLAUDE_TOKEN' > ~/.claude-oauth-token"
echo "Claude token pushed."

cd "$HOST_DIR" && python3 refresh-token.py "$VM_IP" &
REFRESH_PID=$!
cd "$REPO_DIR"

# --- Run the inner script ---
echo "Running sandbox-inner.sh inside VM..."
sshpass -e ssh "${SSH_OPTS[@]}" "admin@$VM_IP" "bash /tmp/computer-workflow/sandbox-inner.sh"
