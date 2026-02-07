#!/usr/bin/env python3
"""Wrapper around gh that injects a token from a file."""

import os
import shutil
import sys
from pathlib import Path

TOKEN_PATH: Path = Path(os.environ["CW_GITHUB_TOKEN_PATH"])

# Find the real gh, skipping this wrapper's directory
this_dir: str = str(Path(__file__).resolve().parent)
path_dirs: list[str] = [d for d in os.environ.get("PATH", "").split(":") if d != this_dir]
real_gh: str | None = shutil.which("gh", path=":".join(path_dirs))

if not real_gh:
    print("Error: could not find real gh", file=sys.stderr)
    sys.exit(1)

os.environ["GH_TOKEN"] = TOKEN_PATH.read_text().strip()
os.execv(real_gh, ["gh"] + sys.argv[1:])
