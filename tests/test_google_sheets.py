from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httplib2
import pytest
from google.auth.exceptions import DefaultCredentialsError, RefreshError

from google_integration.config import ConfigError, GoogleSheetsConfig
from google_integration.google_sheets import (
    GoogleSheetsAPIError,
    GoogleSheetsClient,
    SheetAlreadyExistsError,
    SheetNotFoundError,
)
from tests.auth_failures import (
    RAW_AUTH_DETAIL,
    SHEETS_AUTH_FAILURES,
    SHEETS_AUTH_REASON,
    sheets_client_failing_auth,
    sheets_client_with_raising_credentials,
)
from tests.credential_files import (
    MALFORMED_SERVICE_ACCOUNT_FILES,
    RAW_SECRET,
    SHEETS_INVALID_CREDENTIALS_MESSAGE,
    valid_service_account_file,
    write_credential_file,
)
from tests.transport_failures import (
    PROGRAMMING_ERRORS,
    RAW_DETAIL,
    TRANSPORT_FAILURES,
    sheets_client_failing_with,
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


def test_get_sheet_names_returns_titles(tmp_path: Path) -> None:
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
            credentials_path=write_credential_file(tmp_path, "{}"),
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


def test_read_range_returns_values(tmp_path: Path) -> None:
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
            credentials_path=write_credential_file(tmp_path, "{}"),
            service_builder=service_builder,
        )
        result = client.read_range("Sheet1!A1:B2")

    assert result == [["Name", "Score"], ["Alice", "42"]]
    values.get.assert_called_once_with(
        spreadsheetId="spreadsheet-id",
        range="Sheet1!A1:B2",
    )


def test_read_all_values_reads_full_sheet(tmp_path: Path) -> None:
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
            credentials_path=write_credential_file(tmp_path, "{}"),
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


@pytest.mark.parametrize(("make_error", "reason"), TRANSPORT_FAILURES)
def test_transport_failures_are_wrapped_in_google_sheets_api_error(make_error, reason) -> None:
    error = make_error()
    client, http_stub = sheets_client_failing_with(error)

    with pytest.raises(GoogleSheetsAPIError) as exc_info:
        client.read_range("Sheet1!A1:B2")

    message = str(exc_info.value)
    assert message == (
        "Google Sheets API request failed while reading range 'Sheet1!A1:B2'. "
        f"Network error: {reason}."
    )
    assert RAW_DETAIL not in message
    assert exc_info.value.__cause__ is error
    assert http_stub.calls == 1


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda client: client.get_sheet_names(), id="get-sheet-names"),
        pytest.param(lambda client: client.write_range("Sheet1!A1:A1", [["x"]]), id="write-range"),
        pytest.param(lambda client: client.append_rows("Sheet1!A1:A1", [["x"]]), id="append-rows"),
        pytest.param(lambda client: client.clear_range("Sheet1!A1:A1"), id="clear-range"),
        pytest.param(lambda client: client.create_sheet("New"), id="create-sheet-metadata-lookup"),
        pytest.param(lambda client: client.freeze_rows("Sheet1", 1), id="freeze-rows-metadata-lookup"),
    ],
)
def test_every_sheets_operation_wraps_transport_failures(operation) -> None:
    error = httplib2.ServerNotFoundError(RAW_DETAIL)
    client, _ = sheets_client_failing_with(error)

    with pytest.raises(GoogleSheetsAPIError, match="Network error") as exc_info:
        operation(client)

    assert RAW_DETAIL not in str(exc_info.value)
    assert exc_info.value.__cause__ is error


@pytest.mark.parametrize("make_error", PROGRAMMING_ERRORS)
def test_programming_errors_from_sheets_execute_stay_unexpected(make_error) -> None:
    error = make_error()
    client, _ = sheets_client_failing_with(error)

    with pytest.raises(type(error)) as exc_info:
        client.read_range("Sheet1!A1:B2")

    assert exc_info.value is error


@pytest.mark.parametrize("make_failure", SHEETS_AUTH_FAILURES)
def test_service_account_refresh_failures_are_wrapped_in_google_sheets_api_error(
    make_failure,
) -> None:
    client, fake_http = sheets_client_failing_auth(make_failure)

    with pytest.raises(GoogleSheetsAPIError) as exc_info:
        client.read_range("Sheet1!A1:B2")

    message = str(exc_info.value)
    assert message == (
        "Google Sheets API request failed while reading range 'Sheet1!A1:B2'. "
        f"{SHEETS_AUTH_REASON}"
    )
    assert RAW_AUTH_DETAIL not in message
    assert "invalid_grant" not in message
    assert isinstance(exc_info.value.__cause__, RefreshError)
    assert RAW_AUTH_DETAIL in str(exc_info.value.__cause__)
    assert fake_http.token_requests == 1


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda client: client.get_sheet_names(), id="get-sheet-names"),
        pytest.param(lambda client: client.write_range("Sheet1!A1:A1", [["x"]]), id="write-range"),
        pytest.param(lambda client: client.freeze_rows("Sheet1", 1), id="freeze-rows-metadata-lookup"),
    ],
)
def test_every_sheets_operation_wraps_token_refresh_failures(operation) -> None:
    error = RefreshError(("invalid_grant", {"error_description": RAW_AUTH_DETAIL}))
    client = sheets_client_with_raising_credentials(error)

    with pytest.raises(GoogleSheetsAPIError, match="Authentication error") as exc_info:
        operation(client)

    assert RAW_AUTH_DETAIL not in str(exc_info.value)
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
    client = sheets_client_with_raising_credentials(error)

    with pytest.raises(type(error)) as exc_info:
        client.read_range("Sheet1!A1:B2")

    assert exc_info.value is error


@pytest.mark.parametrize("content", MALFORMED_SERVICE_ACCOUNT_FILES)
def test_malformed_service_account_file_raises_config_error(tmp_path: Path, content) -> None:
    credentials_path = write_credential_file(tmp_path, content)
    service_builder = MagicMock()
    client = GoogleSheetsClient(
        spreadsheet_id="spreadsheet-id",
        credentials_path=credentials_path,
        service_builder=service_builder,
    )

    with pytest.raises(ConfigError) as exc_info:
        client.get_sheet_names()

    message = str(exc_info.value)
    assert message == SHEETS_INVALID_CREDENTIALS_MESSAGE
    assert RAW_SECRET not in message
    assert str(credentials_path) not in message
    # The original parsing/validation error stays available for debugging.
    cause = exc_info.value.__cause__
    assert isinstance(cause, ValueError)
    assert cause is not exc_info.value
    service_builder.assert_not_called()


@pytest.mark.parametrize("operation_name", ["read_range", "write_range", "freeze_rows"])
def test_every_sheets_operation_reports_a_malformed_service_account_file(
    tmp_path: Path, operation_name: str
) -> None:
    client = GoogleSheetsClient(
        spreadsheet_id="spreadsheet-id",
        credentials_path=write_credential_file(tmp_path, "{not json"),
        service_builder=MagicMock(),
    )
    operations = {
        "read_range": lambda: client.read_range("Sheet1!A1:B2"),
        "write_range": lambda: client.write_range("Sheet1!A1:A1", [["x"]]),
        "freeze_rows": lambda: client.freeze_rows("Sheet1", 1),
    }

    with pytest.raises(ConfigError, match="invalid or malformed"):
        operations[operation_name]()


@pytest.mark.parametrize(
    "make_error",
    [
        pytest.param(lambda: TypeError("programming error"), id="type-error"),
        pytest.param(lambda: KeyError("programming error"), id="key-error"),
        pytest.param(lambda: AttributeError("programming error"), id="attribute-error"),
        pytest.param(lambda: RuntimeError("programming error"), id="runtime-error"),
    ],
)
def test_unrelated_errors_while_loading_service_account_credentials_stay_unexpected(
    tmp_path: Path, make_error
) -> None:
    # A well-formed JSON object gets past the file-shape check, so only the library
    # call itself is being simulated. Only ValueError (google-auth's signal for bad
    # file content) is converted at this boundary; nothing else is.
    error = make_error()
    client = GoogleSheetsClient(
        spreadsheet_id="spreadsheet-id",
        credentials_path=write_credential_file(tmp_path, "{}"),
        service_builder=MagicMock(),
    )

    with patch(
        "google_integration.google_sheets.Credentials.from_service_account_file",
        side_effect=error,
    ):
        with pytest.raises(type(error)) as exc_info:
            client.get_sheet_names()

    assert exc_info.value is error


def test_valid_service_account_file_is_still_loaded_by_google_auth(tmp_path: Path) -> None:
    service_builder = MagicMock()
    client = GoogleSheetsClient(
        spreadsheet_id="spreadsheet-id",
        credentials_path=valid_service_account_file(tmp_path),
        service_builder=service_builder,
    )

    client.get_sheet_names()

    credentials = service_builder.call_args.kwargs["credentials"]
    assert credentials.service_account_email == "sa@example.iam.gserviceaccount.com"
    assert list(credentials.scopes) == list(GoogleSheetsClient.DEFAULT_SCOPES)


def test_missing_service_account_file_error_is_not_reclassified(tmp_path: Path) -> None:
    # Existence is checked by config loading; the client does not turn I/O errors into
    # a claim that the file's content is malformed.
    client = GoogleSheetsClient(
        spreadsheet_id="spreadsheet-id",
        credentials_path=tmp_path / "missing.json",
        service_builder=MagicMock(),
    )

    with pytest.raises(FileNotFoundError):
        client.get_sheet_names()
