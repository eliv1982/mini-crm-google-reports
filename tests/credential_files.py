"""Fake Google credential files for the malformed-file regression tests.

Every file is written to a pytest tmp_path and holds no real key material. The real
google-auth / google-auth-oauthlib loaders parse them, so the exception each case
raises is whatever the installed libraries raise (checked against google-auth 2.49).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Placed inside malformed files (and therefore inside the library's own exception
# text) so tests can prove it never reaches a user-facing message.
RAW_SECRET = "raw-credential-secret-0xC0FFEE"

SHEETS_INVALID_CREDENTIALS_MESSAGE = (
    "Google service account credentials file is invalid or malformed. "
    "Check GOOGLE_SERVICE_ACCOUNT_PATH."
)
DRIVE_AUTHENTICATION_MESSAGE = "Failed to authenticate with Google Drive OAuth."

_SERVICE_ACCOUNT_BASE = {
    "type": "service_account",
    "client_email": "sa@example.iam.gserviceaccount.com",
    "token_uri": "https://oauth2.googleapis.com/token",
    "private_key_id": "key-id",
}
_TRUNCATED_PEM = f"-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkq{RAW_SECRET}"


def write_credential_file(directory: Path, content: str | bytes, name: str = "credentials.json") -> Path:
    path = directory / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def _service_account(**overrides: object) -> str:
    info = {**_SERVICE_ACCOUNT_BASE, "private_key": _TRUNCATED_PEM, **overrides}
    return json.dumps({key: value for key, value in info.items() if value is not None})


def _without(field: str) -> str:
    info = {**_SERVICE_ACCOUNT_BASE, "private_key": _TRUNCATED_PEM}
    del info[field]
    return json.dumps(info)


# Service-account files the Sheets client must reject as a ConfigError.
MALFORMED_SERVICE_ACCOUNT_FILES = [
    # The file is not JSON at all (JSONDecodeError, a ValueError).
    pytest.param(f'{{"private_key": "{RAW_SECRET}', id="invalid-json-truncated"),
    pytest.param("", id="empty-file"),
    pytest.param("﻿" + _service_account(), id="utf8-bom-prefixed-json"),
    pytest.param(b"\xff\xfe\x81" + RAW_SECRET.encode(), id="not-utf8-bytes"),
    # Valid JSON, but not the JSON object a credential file must be. google-auth would
    # raise a bare AttributeError from data.keys() for these.
    pytest.param("null", id="json-null"),
    pytest.param(f'["{RAW_SECRET}"]', id="json-list"),
    pytest.param(f'"{RAW_SECRET}"', id="json-string"),
    pytest.param("42", id="json-number"),
    # A JSON object that is not a service-account key (MalformedError).
    pytest.param("{}", id="empty-object"),
    pytest.param(_without("client_email"), id="missing-client-email"),
    pytest.param(_without("token_uri"), id="missing-token-uri"),
    pytest.param(_service_account(private_key=None), id="missing-private-key"),
    pytest.param(
        json.dumps({"installed": {"client_id": "id", "client_secret": RAW_SECRET}}),
        id="oauth-client-secret-file-instead",
    ),
    # Required fields present but unusable.
    pytest.param(_service_account(private_key=f"not a pem {RAW_SECRET}"), id="private-key-not-pem"),
    pytest.param(_service_account(private_key=_TRUNCATED_PEM), id="private-key-truncated-pem"),
    pytest.param(_service_account(private_key=1234), id="private-key-wrong-type"),
    pytest.param(_service_account(private_key=[RAW_SECRET]), id="private-key-list"),
]

# GoogleDriveClient token files: Credentials.from_authorized_user_file.
MALFORMED_OAUTH_TOKEN_FILES = [
    pytest.param(f'{{"token": "{RAW_SECRET}', id="invalid-json-truncated"),
    pytest.param("", id="empty-file"),
    pytest.param(b"\xff\xfe\x81" + RAW_SECRET.encode(), id="not-utf8-bytes"),
    pytest.param("null", id="json-null"),
    pytest.param(f'["{RAW_SECRET}"]', id="json-list"),
    pytest.param("42", id="json-number"),
    pytest.param("{}", id="empty-object"),
    pytest.param(
        json.dumps({"token": RAW_SECRET, "client_id": "id", "client_secret": "secret"}),
        id="missing-refresh-token",
    ),
]

# GoogleDriveClient client-secret files: InstalledAppFlow.from_client_secrets_file.
MALFORMED_OAUTH_CLIENT_SECRET_FILES = [
    pytest.param(f'{{"installed": "{RAW_SECRET}', id="invalid-json-truncated"),
    pytest.param("", id="empty-file"),
    pytest.param(b"\xff\xfe\x81" + RAW_SECRET.encode(), id="not-utf8-bytes"),
    pytest.param("null", id="json-null"),
    pytest.param(f'["{RAW_SECRET}"]', id="json-list"),
    pytest.param("42", id="json-number"),
    pytest.param("{}", id="empty-object"),
    pytest.param(json.dumps({"installed": 5}), id="installed-not-an-object"),
    pytest.param(json.dumps({"installed": {"client_id": RAW_SECRET}}), id="installed-missing-fields"),
    pytest.param(
        json.dumps({"type": "service_account", "private_key": RAW_SECRET}),
        id="service-account-file-instead",
    ),
]


def valid_service_account_file(directory: Path) -> Path:
    """A structurally valid service-account key backed by a freshly generated throwaway RSA key."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return write_credential_file(
        directory,
        json.dumps({**_SERVICE_ACCOUNT_BASE, "private_key": private_key}),
        name="valid-service-account.json",
    )
