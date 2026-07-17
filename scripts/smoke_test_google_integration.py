from __future__ import annotations

from datetime import datetime, timezone

from google_integration import (
    ConfigError,
    GoogleDriveClient,
    GoogleSheetsClient,
    load_google_drive_config,
    load_google_sheets_config,
)

TEST_ROWS = [
    ["Name", "Status", "Amount"],
    ["Alice", "Active", "1000"],
    ["Bob", "Pending", "2500"],
]
COLUMN_WIDTHS = (180, 160, 120)


def _build_range_name(sheet_name: str, start_cell: str, end_cell: str) -> str:
    escaped_sheet_name = sheet_name.replace("'", "''")
    return f"'{escaped_sheet_name}'!{start_cell}:{end_cell}"


def run_smoke_test() -> int:
    drive_config = load_google_drive_config()
    sheets_config = load_google_sheets_config()

    if not drive_config.drive_folder_id:
        raise ConfigError(
            "GOOGLE_DRIVE_FOLDER_ID must be set before running the integration smoke test."
        )

    drive_client = GoogleDriveClient.from_config(drive_config)
    spreadsheet_name = (
        f"mini-crm-integration-smoke-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    )
    spreadsheet_id: str | None = None
    flow_error: Exception | None = None

    try:
        created_file = drive_client.create_google_spreadsheet(
            name=spreadsheet_name,
            parent_folder_id=drive_config.drive_folder_id,
        )
        spreadsheet_id = created_file["id"]

        sheets_client = GoogleSheetsClient.from_config(spreadsheet_id, sheets_config)
        sheet_names = sheets_client.get_sheet_names()
        if not sheet_names:
            raise RuntimeError("Created spreadsheet does not expose any sheets.")

        primary_sheet_name = sheet_names[0]
        target_range = _build_range_name(primary_sheet_name, "A1", "C3")

        sheets_client.write_range(target_range, TEST_ROWS)
        sheets_client.format_range(primary_sheet_name, 0, 1, 0, 3, bold=True)
        sheets_client.freeze_rows(primary_sheet_name, 1)

        for start_column, width_pixels in enumerate(COLUMN_WIDTHS):
            sheets_client.set_column_width(
                primary_sheet_name,
                start_column,
                start_column + 1,
                width_pixels,
            )

        actual_rows = sheets_client.read_range(target_range)
        if actual_rows != TEST_ROWS:
            raise RuntimeError(
                "Read verification failed: the data returned by Google Sheets did not match the written rows."
            )

        print(f"Spreadsheet name: {created_file.get('name', spreadsheet_name)}")
        print(f"Spreadsheet ID: {spreadsheet_id}")
        print(f"Web view link: {created_file.get('webViewLink', '')}")
        print("Sheets write: OK")
        print("Read verification: OK")
    except Exception as error:
        flow_error = error

    cleanup_error: Exception | None = None
    if spreadsheet_id is not None:
        try:
            drive_client.delete_file(spreadsheet_id)
            print("cleanup: OK")
        except Exception as error:
            cleanup_error = error

    if cleanup_error and flow_error:
        raise flow_error from cleanup_error
    if cleanup_error:
        raise cleanup_error
    if flow_error:
        raise flow_error

    return 0


def main() -> int:
    return run_smoke_test()


if __name__ == "__main__":
    raise SystemExit(main())
