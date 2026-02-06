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

This project uses a sandboxed VM architecture to safely run Claude Code on GitHub issues. The system is split into two main components: the **host** and the **sandbox**.

### Components

#### Host (`host/`)

The host runs on your machine and orchestrates the sandbox VM:

- **`build-sandbox.sh`**: Creates and provisions a new macOS VM using [tart](https://github.com/cirruslabs/tart). Copies project files and runs the sandbox build process.
- **`run-sandbox.sh`**: Starts the pre-built VM, copies in credentials and project files, and launches the issue polling loop. Handles cleanup on exit.
- **`refresh-token.py`**: Continuously generates fresh GitHub App installation tokens (every 30 minutes) and pushes them into the sandbox VM via SSH.
- **`github_app_token.py`**: Helper library for generating GitHub App installation tokens from a private key.

#### Sandbox (`sandbox/`)

The sandbox runs inside an isolated macOS VM and processes issues:

- **`get_issues.py`**: The main orchestrator that polls GitHub for open issues, clones the target repo, and invokes Claude Code to resolve each issue. Adds a "claimed" label to issues being processed and filters out pull requests.
- **`sandbox-inner.sh`**: Entry point script that runs inside the VM. Waits for credentials, sets up environment, and starts the issue polling loop.
- **`sandbox-build-inner.sh`**: Runs during VM provisioning to install dependencies (Nix, Claude Code).
- **`gh-wrapper.py`**: Wraps the `gh` CLI tool to automatically inject authentication tokens from a file. Placed in `sandbox/bin/gh` to intercept `gh` commands.
- **`git-credential-app.py`**: Git credential helper that provides authentication tokens from a file for git operations (push, pull, etc.).

#### Nix Configuration (`flake.nix`)

Defines two development environments:

- **`default`**: For the host machine. Includes tart (VM management), sshpass (SSH automation), and PyGithub.
- **`sandbox`**: For the VM environment. Includes Node.js, gh CLI, git, and PyGithub.

### How It Works

1. **Build Phase** (`build-sandbox.sh`):
   - Clones a base macOS VM image
   - Copies project files into the VM
   - Installs Nix and Claude Code
   - Stops and saves the VM for reuse

2. **Run Phase** (`run-sandbox.sh`):
   - Starts the pre-built VM
   - Copies in fresh credentials (GitHub App token, Claude OAuth token)
   - Starts the token refresh loop in the background
   - Executes `sandbox-inner.sh` inside the VM

3. **Issue Processing** (`get_issues.py`):
   - Polls GitHub API for open issues without the "claimed" label
   - Filters out pull requests
   - Claims an issue by adding the "claimed" label
   - Clones the target repository
   - Sets up git credential helper for authentication
   - Invokes Claude Code with a prompt to resolve the issue
   - Streams output as JSON events
   - Repeats in polling mode

4. **Authentication Flow**:
   - Host generates GitHub App installation tokens using the app's private key
   - Tokens are pushed into the VM via SSH every 30 minutes (they expire after 1 hour)
   - `gh-wrapper.py` intercepts `gh` commands and injects the token via `GH_TOKEN`
   - `git-credential-app.py` provides tokens for git operations
   - Claude Code OAuth token is set via `CLAUDE_CODE_OAUTH_TOKEN` environment variable

### Security Model

The sandbox provides isolation between the automation and your host machine:

- Claude Code runs inside a VM with no direct access to your host filesystem
- All credentials are pushed into the VM at runtime (not baked into the image)
- The VM can be destroyed and rebuilt cleanly at any time
- Git operations are scoped to cloned temporary directories within the VM
