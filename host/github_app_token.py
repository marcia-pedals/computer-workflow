from pathlib import Path
from github import Auth, Github

APP_ID = 2805513
INSTALLATION_ID = 108295339


def get_token(private_key_path: str) -> str:
    key = Path(private_key_path).read_text()
    auth = Auth.AppInstallationAuth(
        Auth.AppAuth(APP_ID, key),
        INSTALLATION_ID,
    )
    g = Github(auth=auth)
    return g.requester.auth.token
