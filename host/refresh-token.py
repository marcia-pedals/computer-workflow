#!/usr/bin/env python3
"""Runs on the host. Periodically generates a fresh GitHub App installation
token and pushes it into the sandbox VM via scp."""

import argparse
import os
import subprocess
import time

from github_app_token import get_token

REFRESH_INTERVAL: int = 30 * 60  # 30 minutes (tokens last 1 hour)

SSH_OPTS: list[str] = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "LogLevel=ERROR",
    "-o", "PreferredAuthentications=password",
]


def push_token(private_key: str, app_id: int, installation_id: int, vm_ip: str) -> None:
    token: str = get_token(private_key, app_id, installation_id)
    subprocess.run(
        ["sshpass", "-e", "ssh", *SSH_OPTS, f"admin@{vm_ip}",
         f"echo '{token}' > ~/.github-app-token"],
        env={**os.environ, "SSHPASS": "admin"},
        check=True,
    )
    print(f"Token pushed to {vm_ip}")


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description="Push GitHub App token to sandbox VM")
    parser.add_argument("private_key", help="Path to the GitHub App private key PEM file")
    parser.add_argument("vm_ip", help="IP address of the sandbox VM")
    parser.add_argument("--app-id", type=int, required=True, help="GitHub App ID")
    parser.add_argument("--installation-id", type=int, required=True, help="GitHub App installation ID")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true", help="Push token once and exit")
    group.add_argument("--continuous", action="store_true", help="Push token and keep refreshing")
    args: argparse.Namespace = parser.parse_args()

    push_token(args.private_key, args.app_id, args.installation_id, args.vm_ip)

    if args.continuous:
        while True:
            time.sleep(REFRESH_INTERVAL)
            try:
                push_token(args.private_key, args.app_id, args.installation_id, args.vm_ip)
            except Exception as e:
                print(f"Error pushing token: {e}")


if __name__ == "__main__":
    main()
