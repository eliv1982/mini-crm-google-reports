from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from google_integration.config import GoogleSheetsConfig
from google_integration.google_sheets import (
    GoogleSheetsClient,
    SheetAlreadyExistsError,
    SheetNotFoundError,
)


def _build_client_with_mocks():
    credentials = object()
    service = MagicMock()
    spreadsheets = service.spreadsheets.return_value
    values = spreadsheets.values.return_value
    service_builder = MagicMock(return_value=service)

    return credentials, service, spreadsheets, values, service_builder


def _build_client_with_service():
    service = MagicMock()
    spreadsheets = service.spreadsheets.return_value
    values = spreadsheets.values.return_value
    client = GoogleSheetsClient(
        spreadsheet_id="spreadsheet-id",
        credentials_path="credentials/service-account.json",
        service=service,
    )
    return client, service, spreadsheets, values


def test_from_config_uses_credentials_path_and_spreadsheet_id() -> None:
    config = GoogleSheetsConfig(
        credentials_path=Path("credentials/service-account.json"),
    )

    client = GoogleSheetsClient.from_config("spreadsheet-id", config)

    assert client.spreadsheet_id == "spreadsheet-id"
    assert client.credentials_path == Path("credentials/service-account.json")


def test_get_sheet_names_returns_titles() -> None:
    credentials, _, spreadsheets, _, service_builder = _build_client_with_mocks()
    spreadsheets.get.return_value.execute.return_value = {
        "sheets": [
            {"properties": {"title": "Summary"}},
            {"properties": {"title": "Raw Data"}},
        ]
    }
    with patch(
        "google_integration.google_sheets.Credentials.from_service_account_file",
        return_value=credentials,
    ):
        client = GoogleSheetsClient(
            spreadsheet_id="spreadsheet-id",
            credentials_path="credentials/service-account.json",
            service_builder=service_builder,
        )
        result = client.get_sheet_names()

    assert result == ["Summary", "Raw Data"]
    service_builder.assert_called_once_with(
        "sheets",
        "v4",
        credentials=credentials,
        cache_discovery=False,
    )


def test_read_range_returns_values() -> None:
    credentials, _, _, values, service_builder = _build_client_with_mocks()
    values.get.return_value.execute.return_value = {
        "values": [["Name", "Score"], ["Alice", "42"]]
    }
    with patch(
        "google_integration.google_sheets.Credentials.from_service_account_file",
        return_value=credentials,
    ):
        client = GoogleSheetsClient(
            spreadsheet_id="spreadsheet-id",
            credentials_path="credentials/service-account.json",
            service_builder=service_builder,
        )
        result = client.read_range("Sheet1!A1:B2")

    assert result == [["Name", "Score"], ["Alice", "42"]]
    values.get.assert_called_once_with(
        spreadsheetId="spreadsheet-id",
        range="Sheet1!A1:B2",
    )


def test_read_all_values_reads_full_sheet() -> None:
    credentials, _, _, values, service_builder = _build_client_with_mocks()
    values.get.return_value.execute.return_value = {
        "values": [["A", "B"], ["1", "2"]]
    }
    with patch(
        "google_integration.google_sheets.Credentials.from_service_account_file",
        return_value=credentials,
    ):
        client = GoogleSheetsClient(
            spreadsheet_id="spreadsheet-id",
            credentials_path="credentials/service-account.json",
            service_builder=service_builder,
        )
        result = client.read_all_values("Quarterly Report")

    assert result == [["A", "B"], ["1", "2"]]
    values.get.assert_called_once_with(
        spreadsheetId="spreadsheet-id",
        range="'Quarterly Report'",
    )


def test_get_sheet_id_returns_numeric_id() -> None:
    client, _, spreadsheets, _ = _build_client_with_service()
    spreadsheets.get.return_value.execute.return_value = {
        "sheets": [{"properties": {"title": "Summary", "sheetId": 321}}]
    }

    result = client.get_sheet_id("Summary")

    assert result == 321


def test_create_sheet_creates_new_sheet() -> None:
    client, _, spreadsheets, _ = _build_client_with_service()
    spreadsheets.get.return_value.execute.return_value = {"sheets": []}
    spreadsheets.batchUpdate.return_value.execute.return_value = {
        "replies": [{"addSheet": {"properties": {"sheetId": 777}}}]
    }

    result = client.create_sheet("New Sheet")

    assert result == 777
    spreadsheets.batchUpdate.assert_called_once_with(
        spreadsheetId="spreadsheet-id",
        body={"requests": [{"addSheet": {"properties": {"title": "New Sheet"}}}]},
    )


def test_create_sheet_raises_for_duplicate_name() -> None:
    client, _, spreadsheets, _ = _build_client_with_service()
    spreadsheets.get.return_value.execute.return_value = {
        "sheets": [{"properties": {"title": "Existing"}}]
    }

    with pytest.raises(SheetAlreadyExistsError, match="already exists"):
        client.create_sheet("Existing")

    spreadsheets.batchUpdate.assert_not_called()


def test_delete_sheet_deletes_existing_sheet() -> None:
    client, _, spreadsheets, _ = _build_client_with_service()
    spreadsheets.get.return_value.execute.return_value = {
        "sheets": [{"properties": {"title": "Archive", "sheetId": 9001}}]
    }
    spreadsheets.batchUpdate.return_value.execute.return_value = {"replies": []}

    client.delete_sheet("Archive")

    spreadsheets.batchUpdate.assert_called_once_with(
        spreadsheetId="spreadsheet-id",
        body={"requests": [{"deleteSheet": {"sheetId": 9001}}]},
    )


def test_delete_sheet_raises_for_missing_sheet() -> None:
    client, _, spreadsheets, _ = _build_client_with_service()
    spreadsheets.get.return_value.execute.return_value = {"sheets": []}

    with pytest.raises(SheetNotFoundError, match="was not found"):
        client.delete_sheet("Missing")

    spreadsheets.batchUpdate.assert_not_called()


def test_write_range_uses_raw_input_mode() -> None:
    client, _, _, values = _build_client_with_service()
    values.update.return_value.execute.return_value = {"updatedCells": 2}

    result = client.write_range("Sheet1!A1:B1", [["=1+1", "+7 999 123-45-67"]])

    assert result == {"updatedCells": 2}
    values.update.assert_called_once_with(
        spreadsheetId="spreadsheet-id",
        range="Sheet1!A1:B1",
        valueInputOption="RAW",
        body={"values": [["=1+1", "+7 999 123-45-67"]]},
    )


def test_append_rows_appends_with_insert_rows_mode() -> None:
    client, _, _, values = _build_client_with_service()
    values.append.return_value.execute.return_value = {"updates": {"updatedRows": 2}}

    result = client.append_rows("Sheet1!A:B", [["A", "B"], ["C", "D"]])

    assert result == {"updates": {"updatedRows": 2}}
    values.append.assert_called_once_with(
        spreadsheetId="spreadsheet-id",
        range="Sheet1!A:B",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [["A", "B"], ["C", "D"]]},
    )


def test_clear_range_clears_requested_range() -> None:
    client, _, _, values = _build_client_with_service()
    values.clear.return_value.execute.return_value = {"clearedRange": "Sheet1!A1:B2"}

    result = client.clear_range("Sheet1!A1:B2")

    assert result == {"clearedRange": "Sheet1!A1:B2"}
    values.clear.assert_called_once_with(
        spreadsheetId="spreadsheet-id",
        range="Sheet1!A1:B2",
        body={},
    )


def test_format_range_sends_repeat_cell_request() -> None:
    client, _, spreadsheets, _ = _build_client_with_service()
    spreadsheets.get.return_value.execute.return_value = {
        "sheets": [{"properties": {"title": "Format", "sheetId": 55}}]
    }
    spreadsheets.batchUpdate.return_value.execute.return_value = {"replies": []}

    client.format_range(
        "Format",
        0,
        1,
        0,
        3,
        background_color={"red": 1.0, "green": 0.9, "blue": 0.8},
        bold=True,
        font_size=12,
        horizontal_alignment="CENTER",
        vertical_alignment="MIDDLE",
        wrap_strategy="WRAP",
        number_format={"type": "NUMBER", "pattern": "0.00"},
    )

    spreadsheets.batchUpdate.assert_called_once_with(
        spreadsheetId="spreadsheet-id",
        body={
            "requests": [
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": 55,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": 3,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {
                                    "red": 1.0,
                                    "green": 0.9,
                                    "blue": 0.8,
                                },
                                "textFormat": {"bold": True, "fontSize": 12},
                                "horizontalAlignment": "CENTER",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "WRAP",
                                "numberFormat": {
                                    "type": "NUMBER",
                                    "pattern": "0.00",
                                },
                            }
                        },
                        "fields": (
                            "userEnteredFormat.backgroundColor,"
                            "userEnteredFormat.textFormat.bold,"
                            "userEnteredFormat.textFormat.fontSize,"
                            "userEnteredFormat.horizontalAlignment,"
                            "userEnteredFormat.verticalAlignment,"
                            "userEnteredFormat.wrapStrategy,"
                            "userEnteredFormat.numberFormat"
                        ),
                    }
                }
            ]
        },
    )


def test_merge_cells_sends_merge_request() -> None:
    client, _, spreadsheets, _ = _build_client_with_service()
    spreadsheets.get.return_value.execute.return_value = {
        "sheets": [{"properties": {"title": "Merge", "sheetId": 88}}]
    }
    spreadsheets.batchUpdate.return_value.execute.return_value = {"replies": []}

    client.merge_cells("Merge", 1, 2, 0, 2)

    spreadsheets.batchUpdate.assert_called_once_with(
        spreadsheetId="spreadsheet-id",
        body={
            "requests": [
                {
                    "mergeCells": {
                        "range": {
                            "sheetId": 88,
                            "startRowIndex": 1,
                            "endRowIndex": 2,
                            "startColumnIndex": 0,
                            "endColumnIndex": 2,
                        },
                        "mergeType": "MERGE_ALL",
                    }
                }
            ]
        },
    )


def test_unmerge_cells_sends_unmerge_request() -> None:
    client, _, spreadsheets, _ = _build_client_with_service()
    spreadsheets.get.return_value.execute.return_value = {
        "sheets": [{"properties": {"title": "Merge", "sheetId": 88}}]
    }
    spreadsheets.batchUpdate.return_value.execute.return_value = {"replies": []}

    client.unmerge_cells("Merge", 1, 2, 0, 2)

    spreadsheets.batchUpdate.assert_called_once_with(
        spreadsheetId="spreadsheet-id",
        body={
            "requests": [
                {
                    "unmergeCells": {
                        "range": {
                            "sheetId": 88,
                            "startRowIndex": 1,
                            "endRowIndex": 2,
                            "startColumnIndex": 0,
                            "endColumnIndex": 2,
                        }
                    }
                }
            ]
        },
    )


def test_set_column_width_updates_dimension_properties() -> None:
    client, _, spreadsheets, _ = _build_client_with_service()
    spreadsheets.get.return_value.execute.return_value = {
        "sheets": [{"properties": {"title": "Width", "sheetId": 44}}]
    }
    spreadsheets.batchUpdate.return_value.execute.return_value = {"replies": []}

    client.set_column_width("Width", 0, 3, 180)

    spreadsheets.batchUpdate.assert_called_once_with(
        spreadsheetId="spreadsheet-id",
        body={
            "requests": [
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": 44,
                            "dimension": "COLUMNS",
                            "startIndex": 0,
                            "endIndex": 3,
                        },
                        "properties": {"pixelSize": 180},
                        "fields": "pixelSize",
                    }
                }
            ]
        },
    )


def test_set_row_height_updates_dimension_properties() -> None:
    client, _, spreadsheets, _ = _build_client_with_service()
    spreadsheets.get.return_value.execute.return_value = {
        "sheets": [{"properties": {"title": "Height", "sheetId": 66}}]
    }
    spreadsheets.batchUpdate.return_value.execute.return_value = {"replies": []}

    client.set_row_height("Height", 0, 2, 42)

    spreadsheets.batchUpdate.assert_called_once_with(
        spreadsheetId="spreadsheet-id",
        body={
            "requests": [
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": 66,
                            "dimension": "ROWS",
                            "startIndex": 0,
                            "endIndex": 2,
                        },
                        "properties": {"pixelSize": 42},
                        "fields": "pixelSize",
                    }
                }
            ]
        },
    )


def test_freeze_rows_updates_sheet_properties() -> None:
    client, _, spreadsheets, _ = _build_client_with_service()
    spreadsheets.get.return_value.execute.return_value = {
        "sheets": [{"properties": {"title": "Frozen", "sheetId": 11}}]
    }
    spreadsheets.batchUpdate.return_value.execute.return_value = {"replies": []}

    client.freeze_rows("Frozen", 1)

    spreadsheets.batchUpdate.assert_called_once_with(
        spreadsheetId="spreadsheet-id",
        body={
            "requests": [
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": 11,
                            "gridProperties": {"frozenRowCount": 1},
                        },
                        "fields": "gridProperties.frozenRowCount",
                    }
                }
            ]
        },
    )
