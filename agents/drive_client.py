import os
import threading

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaInMemoryUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]

_service = None
_service_lock = threading.Lock()


def _get_service():
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                creds = service_account.Credentials.from_service_account_file(
                    os.environ["GOOGLE_CREDENTIALS_PATH"],
                    scopes=SCOPES,
                )
                _service = build("drive", "v3", credentials=creds)
    return _service


def create_file(folder_id: str, name: str, content: str) -> str:
    """Creates a plain-text file in Drive. Returns the new file ID."""
    service = _get_service()
    metadata = {"name": name, "parents": [folder_id]}
    media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/plain")
    file = service.files().create(body=metadata, media_body=media, fields="id").execute()
    return file["id"]


def upload_backup(folder_id: str, name: str, file_path: str):
    """Uploads a binary file (the SQLite DB) to Drive as a backup."""
    service = _get_service()
    metadata = {"name": name, "parents": [folder_id]}
    media = MediaFileUpload(file_path, mimetype="application/octet-stream")
    service.files().create(body=metadata, media_body=media).execute()
