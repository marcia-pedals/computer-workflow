#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VM_NAME="vats5-sandbox"
BASE_IMAGE="ghcr.io/cirruslabs/macos-sequoia-base:latest"

# --- Cleanup trap: stop and delete the VM on exit ---
cleanup() {
  echo "Cleaning up VM '$VM_NAME'..."
  tart stop "$VM_NAME" 2>/dev/null || true
  tart delete "$VM_NAME" 2>/dev/null || true
}
trap cleanup EXIT

# --- Create a fresh disposable VM ---
echo "Cloning base image..."
tart delete "$VM_NAME" 2>/dev/null || true
tart clone "$BASE_IMAGE" "$VM_NAME"

# --- Start VM in background with softnet (internet, no host access) ---
echo "Starting VM..."
tart run "$VM_NAME" --net-softnet --no-graphics &
TART_PID=$!

# --- Wait for VM to boot and become SSH-reachable ---
echo "Waiting for VM to become reachable..."
VM_IP=""
for i in $(seq 1 60); do
  VM_IP="$(tart ip "$VM_NAME" 2>/dev/null || true)"
  if [[ -n "$VM_IP" ]]; then
    break
  fi
  sleep 2
done

if [[ -z "$VM_IP" ]]; then
  echo "ERROR: VM did not get an IP after 120s"
  exit 1
fi

echo "VM IP: $VM_IP"

SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o PubkeyAuthentication=no)
export SSHPASS=admin

# Wait for SSH to be ready
for i in $(seq 1 30); do
  if sshpass -e ssh "${SSH_OPTS[@]}" "admin@$VM_IP" true 2>/dev/null; then
    break
  fi
  sleep 2
done

echo "VM is SSH-reachable."

# --- Copy files into the VM ---
echo "Copying files into VM..."
sshpass -e scp "${SSH_OPTS[@]}" \
  "$SCRIPT_DIR/sandbox-inner.sh" \
  "$SCRIPT_DIR/sandbox-nix.conf" \
  "admin@$VM_IP:/tmp/"

# --- Run the inner script ---
echo "Running sandbox-inner.sh inside VM..."
sshpass -e ssh "${SSH_OPTS[@]}" "admin@$VM_IP" "bash /tmp/sandbox-inner.sh"
