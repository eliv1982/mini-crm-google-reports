from __future__ import annotations

import socket
from datetime import datetime
from unittest.mock import Mock

import httplib2
import pytest
from google.auth.exceptions import RefreshError

from google_integration import (
    ConfigError,
    GoogleDriveAuthenticationError,
    GoogleDriveConfig,
    GoogleDriveOperationError,
    GoogleSheetsAPIError,
    GoogleSheetsConfig,
    SheetNotFoundError,
)
from reports import exporter as exporter_module
from reports.exporter import ReportExportError, ReportExporter
from tests.auth_failures import (
    DRIVE_AUTH_FAILURES,
    DRIVE_AUTH_REASON,
    RAW_AUTH_DETAIL,
    SHEETS_AUTH_FAILURES,
    SHEETS_AUTH_REASON,
    drive_client_failing_auth,
    sheets_client_failing_auth,
)
from tests.transport_failures import (
    RAW_DETAIL,
    drive_client_failing_with,
    sheets_client_failing_with,
)


def _build_exporter(
    *,
    clients=None,
    deals=None,
    tasks=None,
    sheet_names=None,
    time_provider=None,
):
    api_client = Mock()
    api_client.get_all_clients.return_value = clients if clients is not None else []
    api_client.get_all_deals.return_value = deals if deals is not None else []
    api_client.get_all_tasks.return_value = tasks if tasks is not None else []

    drive_client = Mock()
    drive_client.create_google_spreadsheet.return_value = {
        "id": "spreadsheet-123",
        "name": "Generated report",
        "webViewLink": "https://example.test/report",
    }
    drive_client.delete_file = Mock()

    sheets_client = Mock()
    sheets_client.get_sheet_names.return_value = sheet_names or ["Custom Sheet"]

    exporter = ReportExporter(
        api_client=api_client,
        drive_client=drive_client,
        sheets_client_factory=Mock(return_value=sheets_client),
        drive_folder_id="folder-123",
        time_provider=time_provider or (lambda: datetime(2026, 7, 17, 12, 45)),
    )
    return exporter, api_client, drive_client, sheets_client


def test_export_clients_report_uses_real_sheet_name_and_returns_link() -> None:
    exporter, api_client, drive_client, sheets_client = _build_exporter(
        clients=[
            {
                "id": 1,
                "name": "Alice",
                "company": "Acme",
                "email": "alice@example.com",
                "phone": "+10000000000",
                "status": "active",
                "created_at": "2026-07-01T10:00:00Z",
                "updated_at": "2026-07-02T10:00:00Z",
            }
        ]
    )

    result = exporter.export_clients_report()

    api_client.check_health.assert_called_once()
    drive_client.create_google_spreadsheet.assert_called_once_with(
        name="Mini CRM - Clients Report - 2026-07-17 12-45",
        parent_folder_id="folder-123",
    )
    exporter.sheets_client_factory.assert_called_once_with("spreadsheet-123")
    assert sheets_client.write_range.call_args.args[0].startswith("'Custom Sheet'!A1:")
    written_rows = sheets_client.write_range.call_args.args[1]
    assert written_rows[0] == ["Mini CRM - Clients Report - 2026-07-17 12-45"]
    assert ["ID", "Name", "Company", "Email", "Phone", "Status", "Created At", "Updated At"] in written_rows
    assert any(row and row[0] == "Total clients" for row in written_rows)
    assert result.web_view_link == "https://example.test/report"
    assert result.records_count == 1


def test_export_deals_report_formats_and_keeps_all_paginated_records() -> None:
    deals = [
        {
            "id": index,
            "title": f"Deal {index}",
            "client_id": index if index % 2 else None,
            "amount": float(index) * 10.0,
            "status": "won" if index % 3 == 0 else "new",
            "expected_close_date": "2026-08-01",
            "created_at": "2026-07-01T10:00:00Z",
            "updated_at": "2026-07-02T10:00:00Z",
        }
        for index in range(1, 102)
    ]
    exporter, api_client, _, sheets_client = _build_exporter(deals=deals)

    result = exporter.export_deals_report()

    written_rows = sheets_client.write_range.call_args.args[1]
    header_index = next(
        index for index, row in enumerate(written_rows) if row and row[0] == "ID" and row[1] == "Title"
    )
    data_rows = written_rows[header_index + 1 :]

    assert len(data_rows) == 101
    assert result.records_count == 101
    assert sheets_client.freeze_rows.called
    assert sheets_client.format_range.call_count >= 4
    assert sheets_client.set_column_width.call_count == 8
    api_client.get_all_deals.assert_called_once()


def test_export_tasks_report_writes_summary_and_data() -> None:
    exporter, _, _, sheets_client = _build_exporter(
        tasks=[
            {
                "id": 1,
                "title": "Task",
                "description": "Follow up",
                "client_id": 1,
                "deal_id": 2,
                "due_date": "2026-07-20",
                "completed": False,
                "created_at": "2026-07-01T10:00:00Z",
                "updated_at": "2026-07-02T10:00:00Z",
            }
        ]
    )

    result = exporter.export_tasks_report()

    written_rows = sheets_client.write_range.call_args.args[1]
    assert any(row[0] == "Completion percentage" for row in written_rows if row)
    assert ["ID", "Title", "Description", "Client ID", "Deal ID", "Due Date", "Completed", "Created At", "Updated At"] in written_rows
    assert result.report_type == "tasks"


def test_exporter_raises_without_deleting_file_when_post_create_step_fails() -> None:
    exporter, _, drive_client, sheets_client = _build_exporter(clients=[])
    sheets_client.get_sheet_names.side_effect = RuntimeError("boom")

    with pytest.raises(ReportExportError, match="spreadsheet_id=spreadsheet-123"):
        exporter.export_clients_report()

    drive_client.delete_file.assert_not_called()


@pytest.mark.parametrize(
    ("failing_step", "error", "expected_cause"),
    [
        (
            "write_range",
            GoogleSheetsAPIError("Google Sheets API request failed while writing range 'A1'. HTTP status: 403."),
            "HTTP status: 403",
        ),
        (
            "freeze_rows",
            SheetNotFoundError("Sheet 'Custom Sheet' was not found."),
            "Sheet 'Custom Sheet' was not found",
        ),
    ],
)
def test_post_create_sheets_failure_keeps_cause_and_partial_export_details(
    failing_step: str, error: Exception, expected_cause: str
) -> None:
    exporter, _, drive_client, sheets_client = _build_exporter(clients=[])
    getattr(sheets_client, failing_step).side_effect = error

    with pytest.raises(ReportExportError) as exc_info:
        exporter.export_clients_report()

    message = str(exc_info.value)
    assert expected_cause in message
    assert "spreadsheet_id=spreadsheet-123" in message
    assert "web_view_link=https://example.test/report" in message
    assert exc_info.value.__cause__ is error
    drive_client.delete_file.assert_not_called()


def test_post_create_failure_reports_empty_spreadsheet_reason() -> None:
    exporter, _, _, sheets_client = _build_exporter(clients=[])
    sheets_client.get_sheet_names.return_value = []

    with pytest.raises(ReportExportError) as exc_info:
        exporter.export_clients_report()

    assert "does not expose any sheets" in str(exc_info.value)
    assert "spreadsheet_id=spreadsheet-123" in str(exc_info.value)


def test_post_create_unexpected_error_is_chained_without_leaking_its_message() -> None:
    exporter, _, _, sheets_client = _build_exporter(clients=[])
    unexpected = KeyError("internal-secret-detail")
    sheets_client.write_range.side_effect = unexpected

    with pytest.raises(ReportExportError) as exc_info:
        exporter.export_clients_report()

    message = str(exc_info.value)
    assert "unexpected KeyError" in message
    assert "internal-secret-detail" not in message
    assert "spreadsheet_id=spreadsheet-123" in message
    assert exc_info.value.__cause__ is unexpected


def test_drive_failure_before_spreadsheet_exists_keeps_typed_error() -> None:
    exporter, _, drive_client, _ = _build_exporter(clients=[])
    error = GoogleDriveOperationError("Google Drive API request failed while creating spreadsheet. HTTP status: 404.")
    drive_client.create_google_spreadsheet.side_effect = error

    with pytest.raises(GoogleDriveOperationError) as exc_info:
        exporter.export_clients_report()

    assert exc_info.value is error
    exporter.sheets_client_factory.assert_not_called()


def test_drive_transport_failure_before_spreadsheet_exists_is_typed_and_chained() -> None:
    exporter, _, _, _ = _build_exporter(clients=[])
    transport_error = httplib2.ServerNotFoundError(RAW_DETAIL)
    exporter.drive_client, _ = drive_client_failing_with(transport_error)

    with pytest.raises(GoogleDriveOperationError) as exc_info:
        exporter.export_clients_report()

    message = str(exc_info.value)
    assert "creating spreadsheet 'Mini CRM - Clients Report - 2026-07-17 12-45'" in message
    assert "Network error: could not connect to Google" in message
    assert RAW_DETAIL not in message
    assert exc_info.value.__cause__ is transport_error
    exporter.sheets_client_factory.assert_not_called()


def test_drive_auth_failure_before_spreadsheet_exists_is_typed_and_chained() -> None:
    exporter, _, _, _ = _build_exporter(clients=[])
    exporter.drive_client, fake_http = drive_client_failing_auth(DRIVE_AUTH_FAILURES[0].values[0])

    with pytest.raises(GoogleDriveAuthenticationError) as exc_info:
        exporter.export_clients_report()

    message = str(exc_info.value)
    assert "creating spreadsheet 'Mini CRM - Clients Report - 2026-07-17 12-45'" in message
    assert DRIVE_AUTH_REASON in message
    assert RAW_AUTH_DETAIL not in message
    assert isinstance(exc_info.value.__cause__, RefreshError)
    assert fake_http.token_requests == 1
    exporter.sheets_client_factory.assert_not_called()


def test_post_create_sheets_auth_failure_keeps_spreadsheet_details_and_typed_cause() -> None:
    exporter, _, drive_client, _ = _build_exporter(clients=[])
    sheets_client, fake_http = sheets_client_failing_auth(
        SHEETS_AUTH_FAILURES[0].values[0], "spreadsheet-123"
    )
    exporter.sheets_client_factory = Mock(return_value=sheets_client)

    with pytest.raises(ReportExportError) as exc_info:
        exporter.export_clients_report()

    message = str(exc_info.value)
    assert SHEETS_AUTH_REASON.rstrip(".") in message
    assert "unexpected" not in message
    assert RAW_AUTH_DETAIL not in message
    assert "spreadsheet_id=spreadsheet-123" in message
    assert "web_view_link=https://example.test/report" in message
    sheets_error = exc_info.value.__cause__
    assert isinstance(sheets_error, GoogleSheetsAPIError)
    assert isinstance(sheets_error.__cause__, RefreshError)
    assert fake_http.token_requests == 1
    drive_client.delete_file.assert_not_called()


def test_post_create_sheets_transport_failure_is_a_known_google_cause() -> None:
    exporter, _, drive_client, _ = _build_exporter(clients=[])
    transport_error = socket.timeout(RAW_DETAIL)
    sheets_client, _ = sheets_client_failing_with(transport_error, "spreadsheet-123")
    exporter.sheets_client_factory = Mock(return_value=sheets_client)

    with pytest.raises(ReportExportError) as exc_info:
        exporter.export_clients_report()

    message = str(exc_info.value)
    assert "Network error: the request timed out" in message
    assert "unexpected" not in message
    assert RAW_DETAIL not in message
    assert "spreadsheet_id=spreadsheet-123" in message
    assert "web_view_link=https://example.test/report" in message
    assert isinstance(exc_info.value.__cause__, GoogleSheetsAPIError)
    assert exc_info.value.__cause__.__cause__ is transport_error
    drive_client.delete_file.assert_not_called()


def test_from_env_requires_drive_folder_id(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        exporter_module,
        "load_google_drive_config",
        lambda: GoogleDriveConfig(tmp_path / "secret.json", tmp_path / "token.json", None),
    )
    monkeypatch.setattr(
        exporter_module,
        "load_google_sheets_config",
        lambda: GoogleSheetsConfig(tmp_path / "service-account.json"),
    )

    with pytest.raises(ReportExportError, match="GOOGLE_DRIVE_FOLDER_ID must be set"):
        ReportExporter.from_env()


def test_from_env_propagates_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_config():
        raise ConfigError("Required environment variable GOOGLE_OAUTH_CLIENT_SECRET_PATH is not set.")

    monkeypatch.setattr(exporter_module, "load_google_drive_config", missing_config)

    with pytest.raises(ConfigError, match="GOOGLE_OAUTH_CLIENT_SECRET_PATH"):
        ReportExporter.from_env()
