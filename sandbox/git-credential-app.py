#!/usr/bin/env python3
"""Git credential helper that reads a token from a file."""

import sys
from pathlib import Path

TOKEN_PATH: Path = Path.home() / ".github-app-token"

if len(sys.argv) > 1 and sys.argv[1] == "get":
    sys.stdin.read()
    token: str = TOKEN_PATH.read_text().strip()
    print(f"username=x-access-token")
    print(f"password={token}")
