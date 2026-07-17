from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

import pytest

from reports.exporter import ReportExportError, ReportExporter


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
