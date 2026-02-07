from pathlib import Path
from github import Auth, Github


def get_token(private_key_path: str, app_id: int, installation_id: int) -> str:
    key: str = Path(private_key_path).read_text()
    auth: Auth.AppInstallationAuth = Auth.AppInstallationAuth(
        Auth.AppAuth(app_id, key),
        installation_id,
    )
    g: Github = Github(auth=auth)
    token: str = g.requester.auth.token  # type: ignore[assignment]
    return token
