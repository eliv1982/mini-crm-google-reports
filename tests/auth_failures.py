"""Simulated token-refresh failures for the Google clients, with no real Google calls.

The clients get a real googleapiclient service behind the real google-auth
AuthorizedHttp and real credential classes; only the HTTP layer underneath is faked.
A token refresh that fails inside execute() therefore raises exactly what production
raises (google.auth.exceptions.RefreshError).
"""

from __future__ import annotations

import json
from typing import Any, Callable

import google_auth_httplib2
import httplib2
import pytest
from google.auth import credentials as auth_credentials
from google.auth import crypt
from google.auth.exceptions import ReauthFailError
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import build

from google_integration import GoogleDriveClient, GoogleSheetsClient

# Placed inside the fake token-endpoint response (and therefore inside the
# RefreshError text) so tests can prove it is not leaked into user-facing messages.
RAW_AUTH_DETAIL = "raw-auth-detail-0xFEEDFACE"

DRIVE_AUTH_REASON = "Authentication error: Google OAuth credentials could not be refreshed."
SHEETS_AUTH_REASON = (
    "Authentication error: Google service account credentials could not be refreshed."
)

_TOKEN_URI = "https://oauth2.googleapis.com/token"


class FakeAuthHttp:
    """Stands in for httplib2.Http: the token endpoint rejects the grant, the API answers."""

    def __init__(self, *, api_status: int = 200) -> None:
        self.api_status = api_status
        self.token_requests = 0

    def request(self, uri: Any, method: str = "GET", *args: Any, **kwargs: Any) -> Any:
        if str(uri) == _TOKEN_URI:
            self.token_requests += 1
            body = json.dumps(
                {
                    "error": "invalid_grant",
                    "error_description": f"Token has been expired or revoked. {RAW_AUTH_DETAIL}",
                }
            ).encode()
            return httplib2.Response({"status": 400}), body
        return httplib2.Response({"status": self.api_status}), b"{}"


class RaisingCredentials(auth_credentials.Credentials):
    """Credentials whose refresh always raises `error` (for subclasses and non-refresh errors)."""

    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error

    def refresh(self, request: Any) -> None:
        raise self.error


class _DummySigner(crypt.Signer):
    """Lets service-account credentials build a JWT assertion without any key material."""

    @property
    def key_id(self) -> str:
        return "dummy-key-id"

    def sign(self, message: Any) -> bytes:
        return b"dummy-signature"


def _oauth_credentials(*, token: str | None = None) -> UserCredentials:
    return UserCredentials(
        token=token,
        refresh_token="revoked-refresh-token",
        token_uri=_TOKEN_URI,
        client_id="client-id",
        client_secret="client-secret",
    )


def _service_account_credentials() -> service_account.Credentials:
    return service_account.Credentials(
        _DummySigner(),
        "sa@example.iam.gserviceaccount.com",
        _TOKEN_URI,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )


# Each entry builds (credentials, fake http) for a refresh that fails inside execute().
DRIVE_AUTH_FAILURES = [
    pytest.param(
        lambda: (_oauth_credentials(), FakeAuthHttp()),
        id="oauth-refresh-rejected-invalid-grant",
    ),
    pytest.param(
        lambda: (_oauth_credentials(token="stale-access-token"), FakeAuthHttp(api_status=401)),
        id="oauth-api-401-then-refresh-rejected",
    ),
    pytest.param(
        lambda: (UserCredentials(token=None), FakeAuthHttp()),
        id="oauth-credentials-cannot-refresh",
    ),
    pytest.param(
        lambda: (RaisingCredentials(ReauthFailError(RAW_AUTH_DETAIL)), FakeAuthHttp()),
        id="oauth-reauth-failure-subclass",
    ),
]

SHEETS_AUTH_FAILURES = [
    pytest.param(
        lambda: (_service_account_credentials(), FakeAuthHttp()),
        id="service-account-grant-rejected-invalid-grant",
    ),
]


def _authorized_service(
    api_name: str, version: str, make_failure: Callable[[], tuple[Any, FakeAuthHttp]]
) -> tuple[Any, FakeAuthHttp]:
    credentials, fake_http = make_failure()
    authorized_http = google_auth_httplib2.AuthorizedHttp(credentials, http=fake_http)
    service = build(api_name, version, http=authorized_http, cache_discovery=False)
    return service, fake_http


def drive_client_failing_auth(
    make_failure: Callable[[], tuple[Any, FakeAuthHttp]],
) -> tuple[GoogleDriveClient, FakeAuthHttp]:
    service, fake_http = _authorized_service("drive", "v3", make_failure)
    client = GoogleDriveClient(
        client_secret_path="credentials/client_secret.json",
        token_path="credentials/token.json",
        service=service,
    )
    return client, fake_http


def sheets_client_failing_auth(
    make_failure: Callable[[], tuple[Any, FakeAuthHttp]],
    spreadsheet_id: str = "spreadsheet-id",
) -> tuple[GoogleSheetsClient, FakeAuthHttp]:
    service, fake_http = _authorized_service("sheets", "v4", make_failure)
    client = GoogleSheetsClient(
        spreadsheet_id=spreadsheet_id,
        credentials_path="credentials/service-account.json",
        service=service,
    )
    return client, fake_http


def drive_client_with_raising_credentials(
    error: BaseException,
) -> GoogleDriveClient:
    client, _ = drive_client_failing_auth(lambda: (RaisingCredentials(error), FakeAuthHttp()))
    return client


def sheets_client_with_raising_credentials(error: BaseException) -> GoogleSheetsClient:
    client, _ = sheets_client_failing_auth(lambda: (RaisingCredentials(error), FakeAuthHttp()))
    return client
