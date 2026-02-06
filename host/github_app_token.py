from pathlib import Path
from github import Auth, Github

APP_ID = 2805513
INSTALLATION_ID = 108295339
PRIVATE_KEY_PATH = Path.home() / "personal-projects/.secrets/clever-computer.2026-02-05.private-key.pem"

_auth = Auth.AppInstallationAuth(
    Auth.AppAuth(APP_ID, PRIVATE_KEY_PATH.read_text()),
    INSTALLATION_ID,
)
_github = Github(auth=_auth)


def get_token() -> str:
    return _github.requester.auth.token
