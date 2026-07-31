from __future__ import annotations

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
TOKEN_DIR = Path(".cache-topspot/youtube")
TOKEN_PATH = TOKEN_DIR / "credentials.json"


def get_credentials(client_secrets_path: str | Path) -> Credentials:
    """Load or authorize YouTube upload credentials for an installed app."""
    client_path = Path(client_secrets_path).expanduser().resolve()
    if not client_path.is_file():
        raise FileNotFoundError(
            f"OAuth client credentials not found: {client_path}"
        )

    credentials: Credentials | None = None
    if TOKEN_PATH.is_file():
        credentials = Credentials.from_authorized_user_file(
            str(TOKEN_PATH),
            [YOUTUBE_UPLOAD_SCOPE],
        )

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if (
        not credentials
        or not credentials.valid
        or not credentials.has_scopes([YOUTUBE_UPLOAD_SCOPE])
    ):
        flow = InstalledAppFlow.from_client_secrets_file(
            str(client_path),
            scopes=[YOUTUBE_UPLOAD_SCOPE],
        )
        credentials = flow.run_local_server(port=0)

    _store_credentials(credentials)
    return credentials


def _store_credentials(credentials: Credentials) -> None:
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    temporary_path = TOKEN_PATH.with_suffix(".tmp")
    temporary_path.write_text(credentials.to_json(), encoding="utf-8")
    try:
        temporary_path.chmod(0o600)
    except OSError:
        pass
    os.replace(temporary_path, TOKEN_PATH)
