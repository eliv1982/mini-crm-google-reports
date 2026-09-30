"""Simulated network failures for the Google clients, with no real network access.

The clients get a real googleapiclient service whose HTTP object raises at the
transport boundary, so the real HttpRequest.execute() path decides which exception
reaches the client's _execute wrapper.
"""

from __future__ import annotations

import errno
import http.client
import socket
import ssl
from typing import Any

import httplib2
import pytest
from google.auth.exceptions import TransportError
from googleapiclient.discovery import build

from google_integration import GoogleDriveClient, GoogleSheetsClient

# Distinctive text placed inside every simulated failure so tests can prove it is
# not leaked into user-facing messages.
RAW_DETAIL = "raw-transport-detail-0xDEADBEEF"

CONNECT_REASON = "could not connect to Google"
TIMEOUT_REASON = "the request timed out"

# (factory for a fresh exception, expected user-facing reason). Every entry is an
# exception that escapes googleapiclient's execute() unchanged when retries are off.
TRANSPORT_FAILURES = [
    pytest.param(
        lambda: httplib2.ServerNotFoundError(f"Unable to find the server at {RAW_DETAIL}"),
        CONNECT_REASON,
        id="dns-server-not-found",
    ),
    pytest.param(lambda: socket.timeout(f"timed out {RAW_DETAIL}"), TIMEOUT_REASON, id="timeout"),
    pytest.param(
        lambda: ConnectionRefusedError(errno.ECONNREFUSED, RAW_DETAIL),
        CONNECT_REASON,
        id="connection-refused",
    ),
    pytest.param(
        lambda: OSError(errno.ENETUNREACH, RAW_DETAIL),
        CONNECT_REASON,
        id="network-unreachable",
    ),
    pytest.param(lambda: ssl.SSLError(1, RAW_DETAIL), CONNECT_REASON, id="tls-failure"),
    pytest.param(
        lambda: http.client.BadStatusLine(RAW_DETAIL),
        CONNECT_REASON,
        id="http-client-exception",
    ),
    pytest.param(
        lambda: TransportError(RAW_DETAIL),
        CONNECT_REASON,
        id="google-auth-transport-error",
    ),
]

# Bugs, not operational failures: they must never be converted into project errors.
PROGRAMMING_ERRORS = [
    pytest.param(lambda: TypeError("programming error"), id="type-error"),
    pytest.param(lambda: KeyError("programming error"), id="key-error"),
    pytest.param(lambda: ValueError("programming error"), id="value-error"),
    pytest.param(lambda: RuntimeError("programming error"), id="runtime-error"),
]


class FailingHttp:
    """Stands in for httplib2.Http: every request raises `error` and is counted."""

    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.calls = 0

    def request(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        raise self.error


def drive_client_failing_with(error: BaseException) -> tuple[GoogleDriveClient, FailingHttp]:
    http_stub = FailingHttp(error)
    service = build("drive", "v3", http=http_stub, cache_discovery=False)
    client = GoogleDriveClient(
        client_secret_path="credentials/client_secret.json",
        token_path="credentials/token.json",
        service=service,
    )
    return client, http_stub


def sheets_client_failing_with(
    error: BaseException, spreadsheet_id: str = "spreadsheet-id"
) -> tuple[GoogleSheetsClient, FailingHttp]:
    http_stub = FailingHttp(error)
    service = build("sheets", "v4", http=http_stub, cache_discovery=False)
    client = GoogleSheetsClient(
        spreadsheet_id=spreadsheet_id,
        credentials_path="credentials/service-account.json",
        service=service,
    )
    return client, http_stub
