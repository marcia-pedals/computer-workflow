from pathlib import Path
from github import Auth, Github


def get_token(private_key_path: str, app_id: int, installation_id: int) -> str:
    key = Path(private_key_path).read_text()
    auth = Auth.AppInstallationAuth(
        Auth.AppAuth(app_id, key),
        installation_id,
    )
    g = Github(auth=auth)
    return g.requester.auth.token
