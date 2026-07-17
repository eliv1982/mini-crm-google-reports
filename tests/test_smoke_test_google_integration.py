from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from google_integration import ConfigError
from google_integration.config import GoogleDriveConfig, GoogleSheetsConfig
from scripts import smoke_test_google_integration


def _build_drive_config() -> GoogleDriveConfig:
    return GoogleDriveConfig(
        client_secret_path=Path("credentials/client_secret.json"),
        token_path=Path("credentials/token.json"),
        drive_folder_id="folder-123",
    )


def _build_sheets_config() -> GoogleSheetsConfig:
    return GoogleSheetsConfig(
        credentials_path=Path("credentials/service-account.json"),
    )


def test_run_smoke_test_orchestrates_full_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    drive_client = MagicMock()
    drive_client.create_google_spreadsheet.return_value = {
        "id": "spreadsheet-123",
        "name": "mini-crm-integration-smoke-20260717-120000",
        "webViewLink": "https://example.test/spreadsheet",
    }
    sheets_client = MagicMock()
    sheets_client.get_sheet_names.return_value = ["Quarterly Report"]
    sheets_client.read_range.return_value = smoke_test_google_integration.TEST_ROWS

    monkeypatch.setattr(
        smoke_test_google_integration,
        "load_google_drive_config",
        lambda: _build_drive_config(),
    )
    monkeypatch.setattr(
        smoke_test_google_integration,
        "load_google_sheets_config",
        lambda: _build_sheets_config(),
    )
    monkeypatch.setattr(
        smoke_test_google_integration.GoogleDriveClient,
        "from_config",
        lambda config: drive_client,
    )
    monkeypatch.setattr(
        smoke_test_google_integration.GoogleSheetsClient,
        "from_config",
        lambda spreadsheet_id, config: sheets_client,
    )

    result = smoke_test_google_integration.run_smoke_test()

    assert result == 0
    drive_client.create_google_spreadsheet.assert_called_once()
    sheets_client.write_range.assert_called_once_with(
        "'Quarterly Report'!A1:C3",
        smoke_test_google_integration.TEST_ROWS,
    )
    sheets_client.format_range.assert_called_once_with(
        "Quarterly Report",
        0,
        1,
        0,
        3,
        bold=True,
    )
    sheets_client.freeze_rows.assert_called_once_with("Quarterly Report", 1)
    assert sheets_client.set_column_width.call_count == 3
    sheets_client.read_range.assert_called_once_with("'Quarterly Report'!A1:C3")
    drive_client.delete_file.assert_called_once_with("spreadsheet-123")


def test_run_smoke_test_requires_drive_folder_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke_test_google_integration,
        "load_google_drive_config",
        lambda: GoogleDriveConfig(
            client_secret_path=Path("credentials/client_secret.json"),
            token_path=Path("credentials/token.json"),
            drive_folder_id=None,
        ),
    )
    monkeypatch.setattr(
        smoke_test_google_integration,
        "load_google_sheets_config",
        lambda: _build_sheets_config(),
    )

    with pytest.raises(ConfigError, match="GOOGLE_DRIVE_FOLDER_ID"):
        smoke_test_google_integration.run_smoke_test()


def test_run_smoke_test_attempts_cleanup_after_sheets_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drive_client = MagicMock()
    drive_client.create_google_spreadsheet.return_value = {
        "id": "spreadsheet-123",
        "name": "mini-crm-integration-smoke-20260717-120000",
        "webViewLink": "https://example.test/spreadsheet",
    }
    sheets_client = MagicMock()
    sheets_client.get_sheet_names.return_value = ["Sheet1"]
    sheets_client.write_range.side_effect = RuntimeError("write failed")

    monkeypatch.setattr(
        smoke_test_google_integration,
        "load_google_drive_config",
        lambda: _build_drive_config(),
    )
    monkeypatch.setattr(
        smoke_test_google_integration,
        "load_google_sheets_config",
        lambda: _build_sheets_config(),
    )
    monkeypatch.setattr(
        smoke_test_google_integration.GoogleDriveClient,
        "from_config",
        lambda config: drive_client,
    )
    monkeypatch.setattr(
        smoke_test_google_integration.GoogleSheetsClient,
        "from_config",
        lambda spreadsheet_id, config: sheets_client,
    )

    with pytest.raises(RuntimeError, match="write failed"):
        smoke_test_google_integration.run_smoke_test()

    drive_client.delete_file.assert_called_once_with("spreadsheet-123")
