#!/usr/bin/env bash
set -euo pipefail

HOST_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$HOST_DIR/.." && pwd)"
SANDBOX_DIR="$REPO_DIR/sandbox"
VM_NAME="computer-workflow-sandbox"
BASE_IMAGE="ghcr.io/cirruslabs/macos-sequoia-base:latest"

# --- Create a fresh VM ---
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

SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o PreferredAuthentications=password -o ConnectTimeout=3)
export SSHPASS=admin

for i in $(seq 1 30); do
  if sshpass -e ssh "${SSH_OPTS[@]}" "admin@$VM_IP" true 2>/dev/null; then break; fi
  sleep 2
done

echo "VM is SSH-reachable."

# --- Copy project files into the VM ---
echo "Copying files into VM..."
sshpass -e scp -r "${SSH_OPTS[@]}" "$SANDBOX_DIR" "admin@$VM_IP:computer-workflow"
sshpass -e scp "${SSH_OPTS[@]}" "$REPO_DIR/flake.nix" "$REPO_DIR/flake.lock" "admin@$VM_IP:computer-workflow/"

# --- Run the build script inside the VM ---
echo "Running sandbox-build-inner.sh inside VM..."
sshpass -e ssh "${SSH_OPTS[@]}" "admin@$VM_IP" "bash computer-workflow/sandbox-build-inner.sh"

# --- Stop VM (preserve for future runs) ---
echo "Stopping VM..."
tart stop "$VM_NAME" 2>/dev/null || true
echo "Build complete. VM '$VM_NAME' is ready for use with run-sandbox.sh."
