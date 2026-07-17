from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from google_integration.config import GoogleDriveConfig


class GoogleDriveError(RuntimeError):
    """Base exception for Google Drive client errors."""


class GoogleDriveValidationError(GoogleDriveError):
    """Raised when provided client arguments are invalid."""


class GoogleDriveAuthenticationError(GoogleDriveError):
    """Raised when Google Drive OAuth authentication fails."""


class GoogleDriveOperationError(GoogleDriveError):
    """Raised when a Google Drive API request fails."""


class GoogleDriveClient:
    DEFAULT_SCOPES = ("https://www.googleapis.com/auth/drive",)
    FILE_FIELDS = "id,name,mimeType,webViewLink,createdTime"
    LIST_FIELDS = f"files({FILE_FIELDS})"
    SPREADSHEET_MIME_TYPE = "application/vnd.google-apps.spreadsheet"

    def __init__(
        self,
        client_secret_path: str | Path,
        token_path: str | Path,
        scopes: Sequence[str] | None = None,
        credentials: Credentials | None = None,
        service: Any | None = None,
        flow_factory: Any = InstalledAppFlow.from_client_secrets_file,
        service_builder: Any = build,
        request_factory: Any = Request,
        credentials_loader: Any = Credentials.from_authorized_user_file,
    ) -> None:
        self.client_secret_path = Path(client_secret_path)
        self.token_path = Path(token_path)
        self.scopes = tuple(scopes or self.DEFAULT_SCOPES)
        self._credentials = credentials
        self._service = service
        self._flow_factory = flow_factory
        self._service_builder = service_builder
        self._request_factory = request_factory
        self._credentials_loader = credentials_loader

    @classmethod
    def from_config(
        cls,
        config: GoogleDriveConfig,
        scopes: Sequence[str] | None = None,
    ) -> "GoogleDriveClient":
        return cls(
            client_secret_path=config.client_secret_path,
            token_path=config.token_path,
            scopes=scopes,
        )

    def authenticate(self) -> Credentials:
        credentials = self._credentials
        credentials_updated = False

        try:
            if credentials is None and self.token_path.is_file():
                credentials = self._credentials_loader(
                    str(self.token_path),
                    scopes=list(self.scopes),
                )

            if (
                credentials is not None
                and getattr(credentials, "expired", False)
                and getattr(credentials, "refresh_token", None)
            ):
                credentials.refresh(self._request_factory())
                credentials_updated = True

            if credentials is None or not getattr(credentials, "valid", False):
                flow = self._flow_factory(
                    str(self.client_secret_path),
                    scopes=list(self.scopes),
                )
                credentials = flow.run_local_server(port=0)
                credentials_updated = True

            if credentials is None or not getattr(credentials, "valid", False):
                raise GoogleDriveAuthenticationError(
                    "Google Drive OAuth did not return valid credentials."
                )

            if credentials_updated:
                self._save_credentials(credentials)
        except GoogleDriveError:
            raise
        except Exception as error:
            raise GoogleDriveAuthenticationError(
                "Failed to authenticate with Google Drive OAuth."
            ) from error

        self._credentials = credentials
        return credentials

    def _save_credentials(self, credentials: Credentials) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(credentials.to_json(), encoding="utf-8")

    def _get_service(self) -> Any:
        if self._service is None:
            self._service = self._service_builder(
                "drive",
                "v3",
                credentials=self.authenticate(),
                cache_discovery=False,
            )
        return self._service

    def _files_resource(self) -> Any:
        return self._get_service().files()

    def _execute(self, request: Any, action: str) -> Any:
        try:
            return request.execute()
        except HttpError as error:
            status_code = getattr(error.resp, "status", "unknown")
            raise GoogleDriveOperationError(
                f"Google Drive API request failed while {action}. "
                f"HTTP status: {status_code}."
            ) from error

    @staticmethod
    def _validate_text(value: str, label: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise GoogleDriveValidationError(f"{label} must not be empty.")
        return normalized

    def list_files(self, folder_id: str | None = None) -> list[dict[str, Any]]:
        query_parts = ["trashed = false"]
        if folder_id is not None:
            normalized_folder_id = self._validate_text(folder_id, "Folder ID")
            query_parts.insert(0, f"'{normalized_folder_id}' in parents")

        request = self._files_resource().list(
            q=" and ".join(query_parts),
            fields=self.LIST_FIELDS,
            spaces="drive",
        )
        response = self._execute(request, "listing files")
        return response.get("files", [])

    def create_google_spreadsheet(
        self,
        name: str,
        parent_folder_id: str,
    ) -> dict[str, Any]:
        normalized_name = self._validate_text(name, "Spreadsheet name")
        normalized_folder_id = self._validate_text(parent_folder_id, "Parent folder ID")
        request = self._files_resource().create(
            body={
                "name": normalized_name,
                "mimeType": self.SPREADSHEET_MIME_TYPE,
                "parents": [normalized_folder_id],
            },
            fields=self.FILE_FIELDS,
        )
        return self._execute(request, f"creating spreadsheet '{normalized_name}'")

    def get_file(self, file_id: str) -> dict[str, Any]:
        normalized_file_id = self._validate_text(file_id, "File ID")
        request = self._files_resource().get(
            fileId=normalized_file_id,
            fields=self.FILE_FIELDS,
        )
        return self._execute(request, f"fetching file '{normalized_file_id}'")

    def delete_file(self, file_id: str) -> None:
        normalized_file_id = self._validate_text(file_id, "File ID")
        request = self._files_resource().delete(fileId=normalized_file_id)
        self._execute(request, f"deleting file '{normalized_file_id}'")
