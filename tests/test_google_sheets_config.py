from __future__ import annotations

from pathlib import Path

import pytest

from google_integration.config import ConfigError, load_google_sheets_config


def test_load_google_sheets_config_raises_when_required_env_var_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_PATH", raising=False)

    with pytest.raises(ConfigError, match="GOOGLE_SERVICE_ACCOUNT_PATH"):
        load_google_sheets_config(env_file=tmp_path / ".env")


def test_load_google_sheets_config_raises_when_credentials_file_does_not_exist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing_credentials = tmp_path / "service-account.json"
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_PATH", str(missing_credentials))

    with pytest.raises(ConfigError, match="service account file was not found"):
        load_google_sheets_config(env_file=tmp_path / ".env")


def test_load_google_sheets_config_returns_resolved_absolute_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    credentials_path = tmp_path / "service-account.json"
    credentials_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_PATH", str(credentials_path))

    config = load_google_sheets_config(env_file=tmp_path / ".env")

    assert config.credentials_path == credentials_path.resolve()
