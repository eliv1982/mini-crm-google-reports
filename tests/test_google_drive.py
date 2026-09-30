from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import httplib2
import pytest
from google.auth.exceptions import DefaultCredentialsError, RefreshError
from googleapiclient.errors import HttpError

from google_integration.config import ConfigError, GoogleDriveConfig, load_google_drive_config
from google_integration.google_drive import (
    GoogleDriveAuthenticationError,
    GoogleDriveClient,
    GoogleDriveOperationError,
)
from tests.auth_failures import (
    DRIVE_AUTH_FAILURES,
    DRIVE_AUTH_REASON,
    RAW_AUTH_DETAIL,
    drive_client_failing_auth,
    drive_client_with_raising_credentials,
)
from tests.credential_files import (
    DRIVE_AUTHENTICATION_MESSAGE,
    MALFORMED_OAUTH_CLIENT_SECRET_FILES,
    MALFORMED_OAUTH_TOKEN_FILES,
    RAW_SECRET,
    write_credential_file,
)
from tests.transport_failures import (
    PROGRAMMING_ERRORS,
    RAW_DETAIL,
    TRANSPORT_FAILURES,
    drive_client_failing_with,
)


def _build_credentials(
    *,
    valid: bool,
    expired: bool = False,
    refresh_token: str | None = None,
    token_json: str = '{"token": "test-token"}',
) -> MagicMock:
    credentials = MagicMock()
    credentials.valid = valid
    credentials.expired = expired
    credentials.refresh_token = refresh_token
    credentials.to_json.return_value = token_json
    return credentials


def _build_drive_service():
    service = MagicMock()
    files = service.files.return_value
    return service, files


def _build_http_error(status: int) -> HttpError:
    response = SimpleNamespace(status=status, reason="error")
    return HttpError(response, b"{}")


def test_load_google_drive_config_requires_client_secret_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET_PATH", raising=False)
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_PATH", "credentials/token.json")

    with pytest.raises(ConfigError, match="GOOGLE_OAUTH_CLIENT_SECRET_PATH"):
        load_google_drive_config(env_file=tmp_path / ".env")


def test_load_google_drive_config_returns_optional_folder_id_as_none(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client_secret_path = tmp_path / "client_secret.json"
    client_secret_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET_PATH", str(client_secret_path))
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_PATH", "credentials/token.json")
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "")

    config = load_google_drive_config(env_file=tmp_path / ".env")

    assert config.client_secret_path == client_secret_path.resolve()
    assert config.token_path.name == "token.json"
    assert config.drive_folder_id is None


def test_from_config_uses_drive_paths() -> None:
    config = GoogleDriveConfig(
        client_secret_path=Path("credentials/client_secret.json"),
        token_path=Path("credentials/token.json"),
        drive_folder_id="folder-123",
    )

    client = GoogleDriveClient.from_config(config)

    assert client.client_secret_path == Path("credentials/client_secret.json")
    assert client.token_path == Path("credentials/token.json")


def test_lazy_initialization_delays_auth_and_service_creation(tmp_path: Path) -> None:
    token_path = tmp_path / "token.json"
    token_path.write_text("{}", encoding="utf-8")
    credentials_loader = MagicMock(return_value=_build_credentials(valid=True))
    service, files = _build_drive_service()
    files.list.return_value.execute.return_value = {"files": []}
    service_builder = MagicMock(return_value=service)

    client = GoogleDriveClient(
        client_secret_path=tmp_path / "client_secret.json",
        token_path=token_path,
        credentials_loader=credentials_loader,
        service_builder=service_builder,
    )

    credentials_loader.assert_not_called()
    service_builder.assert_not_called()

    result = client.list_files()

    assert result == []
    credentials_loader.assert_called_once()
    service_builder.assert_called_once()


def test_authenticate_uses_existing_valid_token_file(tmp_path: Path) -> None:
    token_path = tmp_path / "token.json"
    token_path.write_text("{}", encoding="utf-8")
    credentials = _build_credentials(valid=True)
    credentials_loader = MagicMock(return_value=credentials)
    flow_factory = MagicMock()

    client = GoogleDriveClient(
        client_secret_path=tmp_path / "client_secret.json",
        token_path=token_path,
        credentials_loader=credentials_loader,
        flow_factory=flow_factory,
    )

    result = client.authenticate()

    assert result is credentials
    credentials_loader.assert_called_once_with(
        str(token_path),
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    flow_factory.assert_not_called()


def test_authenticate_refreshes_expired_token_and_saves_it(tmp_path: Path) -> None:
    token_path = tmp_path / "token.json"
    token_path.write_text("{}", encoding="utf-8")
    credentials = _build_credentials(valid=False, expired=True, refresh_token="refresh-me")

    def refresh(_: object) -> None:
        credentials.valid = True
        credentials.expired = False

    credentials.refresh.side_effect = refresh
    request = object()
    client = GoogleDriveClient(
        client_secret_path=tmp_path / "client_secret.json",
        token_path=token_path,
        credentials_loader=MagicMock(return_value=credentials),
        request_factory=MagicMock(return_value=request),
    )

    result = client.authenticate()

    assert result is credentials
    credentials.refresh.assert_called_once_with(request)
    assert token_path.read_text(encoding="utf-8") == '{"token": "test-token"}'


def test_authenticate_runs_installed_app_flow_when_token_is_missing(
    tmp_path: Path,
) -> None:
    token_path = tmp_path / "nested" / "token.json"
    credentials = _build_credentials(valid=True, token_json='{"token": "new-token"}')
    flow = MagicMock()
    flow.run_local_server.return_value = credentials
    flow_factory = MagicMock(return_value=flow)

    client = GoogleDriveClient(
        client_secret_path=tmp_path / "client_secret.json",
        token_path=token_path,
        flow_factory=flow_factory,
    )

    result = client.authenticate()

    assert result is credentials
    flow_factory.assert_called_once_with(
        str(tmp_path / "client_secret.json"),
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    flow.run_local_server.assert_called_once_with(port=0)
    assert token_path.read_text(encoding="utf-8") == '{"token": "new-token"}'


def test_authenticate_wraps_oauth_failures(tmp_path: Path) -> None:
    flow_factory = MagicMock(side_effect=RuntimeError("oauth failed"))
    client = GoogleDriveClient(
        client_secret_path=tmp_path / "client_secret.json",
        token_path=tmp_path / "token.json",
        flow_factory=flow_factory,
    )

    with pytest.raises(GoogleDriveAuthenticationError, match="Failed to authenticate"):
        client.authenticate()


# The malformed-file tests below run the real google-auth token loader and the real
# google-auth-oauthlib client-secret parser against fake files. Both raise a mix of
# JSONDecodeError, UnicodeDecodeError, ValueError, TypeError and AttributeError; all of
# them already end up as a GoogleDriveAuthenticationError because authenticate() wraps
# the whole credential-loading step.


def _assert_safe_authentication_error(exc_info, *credential_paths: Path) -> None:
    message = str(exc_info.value)
    assert message == DRIVE_AUTHENTICATION_MESSAGE
    assert RAW_SECRET not in message
    for credential_path in credential_paths:
        assert str(credential_path) not in message
    assert exc_info.value.__cause__ is not None
    assert not isinstance(exc_info.value.__cause__, GoogleDriveAuthenticationError)


@pytest.mark.parametrize("content", MALFORMED_OAUTH_TOKEN_FILES)
def test_malformed_oauth_token_file_raises_authentication_error(tmp_path: Path, content) -> None:
    token_path = write_credential_file(tmp_path, content, "token.json")
    flow_factory = MagicMock()
    client = GoogleDriveClient(
        client_secret_path=tmp_path / "client_secret.json",
        token_path=token_path,
        flow_factory=flow_factory,
    )

    with pytest.raises(GoogleDriveAuthenticationError) as exc_info:
        client.authenticate()

    _assert_safe_authentication_error(exc_info, token_path)
    flow_factory.assert_not_called()


@pytest.mark.parametrize("content", MALFORMED_OAUTH_CLIENT_SECRET_FILES)
def test_malformed_oauth_client_secret_file_raises_authentication_error(
    tmp_path: Path, content
) -> None:
    client_secret_path = write_credential_file(tmp_path, content, "client_secret.json")
    client = GoogleDriveClient(
        client_secret_path=client_secret_path,
        token_path=tmp_path / "token.json",
    )

    with pytest.raises(GoogleDriveAuthenticationError) as exc_info:
        client.authenticate()

    _assert_safe_authentication_error(exc_info, client_secret_path)
    assert not (tmp_path / "token.json").exists()


def test_every_drive_operation_reports_a_malformed_credential_file(tmp_path: Path) -> None:
    client = GoogleDriveClient(
        client_secret_path=write_credential_file(tmp_path, "{not json", "client_secret.json"),
        token_path=tmp_path / "token.json",
        service_builder=MagicMock(),
    )

    with pytest.raises(GoogleDriveAuthenticationError, match="Failed to authenticate"):
        client.list_files()


def test_list_files_with_folder_id_filters_by_parent() -> None:
    service, files = _build_drive_service()
    files.list.return_value.execute.return_value = {
        "files": [{"id": "1", "name": "Sheet"}]
    }
    client = GoogleDriveClient(
        client_secret_path="credentials/client_secret.json",
        token_path="credentials/token.json",
        service=service,
    )

    result = client.list_files("folder-123")

    assert result == [{"id": "1", "name": "Sheet"}]
    files.list.assert_called_once_with(
        q="'folder-123' in parents and trashed = false",
        fields="files(id,name,mimeType,webViewLink,createdTime)",
        spaces="drive",
    )


def test_list_files_without_folder_id_lists_non_trashed_files() -> None:
    service, files = _build_drive_service()
    files.list.return_value.execute.return_value = {"files": []}
    client = GoogleDriveClient(
        client_secret_path="credentials/client_secret.json",
        token_path="credentials/token.json",
        service=service,
    )

    client.list_files()

    files.list.assert_called_once_with(
        q="trashed = false",
        fields="files(id,name,mimeType,webViewLink,createdTime)",
        spaces="drive",
    )


def test_create_google_spreadsheet_uses_native_mimetype_and_parent() -> None:
    service, files = _build_drive_service()
    files.create.return_value.execute.return_value = {
        "id": "spreadsheet-1",
        "name": "CRM Export",
        "webViewLink": "https://example.test/file",
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "createdTime": "2026-07-17T10:00:00Z",
    }
    client = GoogleDriveClient(
        client_secret_path="credentials/client_secret.json",
        token_path="credentials/token.json",
        service=service,
    )

    result = client.create_google_spreadsheet("CRM Export", "folder-123")

    assert result["id"] == "spreadsheet-1"
    assert result["name"] == "CRM Export"
    assert result["webViewLink"] == "https://example.test/file"
    files.create.assert_called_once_with(
        body={
            "name": "CRM Export",
            "mimeType": "application/vnd.google-apps.spreadsheet",
            "parents": ["folder-123"],
        },
        fields="id,name,mimeType,webViewLink,createdTime",
    )


def test_get_file_returns_compact_metadata() -> None:
    service, files = _build_drive_service()
    files.get.return_value.execute.return_value = {
        "id": "file-123",
        "name": "CRM Export",
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "webViewLink": "https://example.test/file",
        "createdTime": "2026-07-17T10:00:00Z",
    }
    client = GoogleDriveClient(
        client_secret_path="credentials/client_secret.json",
        token_path="credentials/token.json",
        service=service,
    )

    result = client.get_file("file-123")

    assert result["id"] == "file-123"
    files.get.assert_called_once_with(
        fileId="file-123",
        fields="id,name,mimeType,webViewLink,createdTime",
    )


def test_delete_file_calls_drive_api_delete() -> None:
    service, files = _build_drive_service()
    files.delete.return_value.execute.return_value = None
    client = GoogleDriveClient(
        client_secret_path="credentials/client_secret.json",
        token_path="credentials/token.json",
        service=service,
    )

    client.delete_file("file-123")

    files.delete.assert_called_once_with(fileId="file-123")


def test_http_errors_are_wrapped_in_google_drive_operation_error() -> None:
    service, files = _build_drive_service()
    files.list.return_value.execute.side_effect = _build_http_error(403)
    client = GoogleDriveClient(
        client_secret_path="credentials/client_secret.json",
        token_path="credentials/token.json",
        service=service,
    )

    with pytest.raises(GoogleDriveOperationError, match="HTTP status: 403"):
        client.list_files()


@pytest.mark.parametrize(("make_error", "reason"), TRANSPORT_FAILURES)
def test_transport_failures_are_wrapped_in_google_drive_operation_error(make_error, reason) -> None:
    error = make_error()
    client, http_stub = drive_client_failing_with(error)

    with pytest.raises(GoogleDriveOperationError) as exc_info:
        client.create_google_spreadsheet("CRM Export", "folder-123")

    message = str(exc_info.value)
    assert message == (
        "Google Drive API request failed while creating spreadsheet 'CRM Export'. "
        f"Network error: {reason}."
    )
    assert RAW_DETAIL not in message
    assert exc_info.value.__cause__ is error
    assert http_stub.calls == 1


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda client: client.list_files(), id="list-files"),
        pytest.param(lambda client: client.list_files("folder-123"), id="list-folder"),
        pytest.param(lambda client: client.get_file("file-123"), id="get-file"),
        pytest.param(lambda client: client.delete_file("file-123"), id="delete-file"),
    ],
)
def test_every_drive_operation_wraps_transport_failures(operation) -> None:
    error = httplib2.ServerNotFoundError(RAW_DETAIL)
    client, _ = drive_client_failing_with(error)

    with pytest.raises(GoogleDriveOperationError, match="Network error") as exc_info:
        operation(client)

    assert RAW_DETAIL not in str(exc_info.value)
    assert exc_info.value.__cause__ is error


@pytest.mark.parametrize("make_error", PROGRAMMING_ERRORS)
def test_programming_errors_from_drive_execute_stay_unexpected(make_error) -> None:
    error = make_error()
    client, _ = drive_client_failing_with(error)

    with pytest.raises(type(error)) as exc_info:
        client.create_google_spreadsheet("CRM Export", "folder-123")

    assert exc_info.value is error


@pytest.mark.parametrize("make_failure", DRIVE_AUTH_FAILURES)
def test_token_refresh_failures_are_wrapped_in_google_drive_authentication_error(
    make_failure,
) -> None:
    client, fake_http = drive_client_failing_auth(make_failure)

    with pytest.raises(GoogleDriveAuthenticationError) as exc_info:
        client.create_google_spreadsheet("CRM Export", "folder-123")

    message = str(exc_info.value)
    assert message == (
        "Google Drive API request failed while creating spreadsheet 'CRM Export'. "
        f"{DRIVE_AUTH_REASON}"
    )
    assert RAW_AUTH_DETAIL not in message
    assert "invalid_grant" not in message
    assert isinstance(exc_info.value.__cause__, RefreshError)
    assert fake_http.token_requests <= 1  # no retries


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda client: client.list_files(), id="list-files"),
        pytest.param(lambda client: client.get_file("file-123"), id="get-file"),
        pytest.param(lambda client: client.delete_file("file-123"), id="delete-file"),
    ],
)
def test_every_drive_operation_wraps_token_refresh_failures(operation) -> None:
    error = RefreshError(("invalid_grant", {"error_description": RAW_AUTH_DETAIL}))
    client = drive_client_with_raising_credentials(error)

    with pytest.raises(GoogleDriveAuthenticationError, match="Authentication error") as exc_info:
        operation(client)

    assert RAW_AUTH_DETAIL not in str(exc_info.value)
    assert exc_info.value.__cause__ is error


def test_refresh_failure_during_authenticate_stays_a_drive_authentication_error(
    tmp_path: Path,
) -> None:
    token_path = tmp_path / "token.json"
    token_path.write_text("{}", encoding="utf-8")
    error = RefreshError("invalid_grant")
    credentials = _build_credentials(valid=False, expired=True, refresh_token="refresh-me")
    credentials.refresh.side_effect = error
    client = GoogleDriveClient(
        client_secret_path=tmp_path / "client_secret.json",
        token_path=token_path,
        credentials_loader=MagicMock(return_value=credentials),
    )

    with pytest.raises(GoogleDriveAuthenticationError, match="Failed to authenticate") as exc_info:
        client.authenticate()

    assert exc_info.value.__cause__ is error


@pytest.mark.parametrize(
    "make_error",
    [
        *PROGRAMMING_ERRORS,
        # Auth errors that are not a failed token refresh are deliberately not caught.
        pytest.param(lambda: DefaultCredentialsError("unrelated"), id="non-refresh-google-auth-error"),
    ],
)
def test_unrelated_errors_raised_while_refreshing_credentials_stay_unexpected(make_error) -> None:
    error = make_error()
    client = drive_client_with_raising_credentials(error)

    with pytest.raises(type(error)) as exc_info:
        client.create_google_spreadsheet("CRM Export", "folder-123")

    assert exc_info.value is error
