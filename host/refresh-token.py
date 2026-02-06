#!/usr/bin/env python3
"""Runs on the host. Periodically generates a fresh GitHub App installation
token and pushes it into the sandbox VM via scp."""

import os
import subprocess
import sys
import time

from github_app_token import get_token

REFRESH_INTERVAL = 30 * 60  # 30 minutes (tokens last 1 hour)

SSH_OPTS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "LogLevel=ERROR",
    "-o", "PubkeyAuthentication=no",
]


def push_token(vm_ip: str):
    token = get_token()
    subprocess.run(
        ["sshpass", "-e", "ssh", *SSH_OPTS, f"admin@{vm_ip}",
         f"echo '{token}' > ~/.github-app-token"],
        env={**os.environ, "SSHPASS": "admin"},
        check=True,
    )
    print(f"Token pushed to {vm_ip}")


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <vm-ip>")
        sys.exit(1)

    vm_ip = sys.argv[1]

    # Initial token is pushed by run-sandbox.sh, so sleep first
    while True:
        time.sleep(REFRESH_INTERVAL)
        try:
            push_token(vm_ip)
        except Exception as e:
            print(f"Error pushing token: {e}")


if __name__ == "__main__":
    main()
