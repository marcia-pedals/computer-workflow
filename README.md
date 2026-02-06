# computer-workflow 🤖

The computer watches your GitHub Issues and makes PRs for them.

```
 _______________
|  ___________  |
| |           | |
| |   HELLO   | |
| |   WORLD   | |
| |___________| |
|_______________|
    _[_____]_
   [_________]
```

## Architecture

### How it works

1. **Polling Loop**: `do_work.py` polls GitHub for unclaimed issues
2. **Issue Processing**: For each issue, it clones the repo and runs Claude Code headless with the issue prompt
3. **Sandboxed Execution**: Claude Code works autonomously to create a PR or comment on the issue

### Sandbox (VM Isolation)

The system runs Claude Code inside a **macOS VM** (via [Tart](https://github.com/cirruslabs/tart)) to isolate operations:

- **Host** (`host/`): Orchestrates VM lifecycle and token management
  - `build-sandbox.sh`: Creates a fresh VM from base image and installs dependencies
  - `run-sandbox.sh`: Starts the VM, copies code, pushes tokens, and runs the polling loop
  - `refresh-token.py`: Periodically generates fresh GitHub App tokens (every 30 min) and pushes them to the VM via SSH

- **Sandbox** (`sandbox/`): Runs inside the VM
  - `do_work.py`: Main script that polls issues and invokes Claude Code
  - `gh-wrapper.py`: Wrapper around `gh` CLI that injects the GitHub token from a file
  - `git-credential-app.py`: Git credential helper that provides the GitHub token for git operations
  - `sandbox-inner.sh`: Entry point that starts the polling loop inside the VM

### Keys and Tokens

- **GitHub App Private Key**: Used by the host to generate installation tokens. Passed to `run-sandbox.sh` via environment config JSON.
- **GitHub App Installation Token**: Short-lived (1 hour) token generated from the private key. Refreshed every 30 minutes and pushed to the VM at `~/.github-app-token`.
- **Claude Code OAuth Token**: Personal token for Claude Code authentication. Pushed to the VM at `~/.claude-oauth-token` during VM startup.

The token architecture ensures:
- The VM never has access to the long-lived private key
- Tokens are automatically refreshed before expiration
- Git and GitHub CLI operations work seamlessly via credential helpers and wrappers
