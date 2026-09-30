from __future__ import annotations

import argparse
import sys

from google_integration import ConfigError, GoogleDriveError, GoogleSheetsError
from reports import (
    EXPECTED_EXPORT_ERRORS,
    CRMAPIError,
    ReportExportError,
    ReportExportResult,
    ReportExporter,
)

# (exception family, message prefix, optional hint), checked in order.
_ERROR_PRESENTATION: tuple[tuple[type[Exception], str, str | None], ...] = (
    (
        ConfigError,
        "Configuration error",
        "Check the Google settings in your .env file (see .env.example).",
    ),
    (
        CRMAPIError,
        "Backend error",
        "Make sure the backend is running and BACKEND_URL is correct.",
    ),
    (
        GoogleDriveError,
        "Google Drive error",
        "Check GOOGLE_DRIVE_FOLDER_ID and your Google OAuth credentials.",
    ),
    (
        GoogleSheetsError,
        "Google Sheets error",
        "Check GOOGLE_SERVICE_ACCOUNT_PATH and that the service account can edit "
        "files in the Drive folder.",
    ),
    (ReportExportError, "Report export failed", None),
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Mini CRM reports to Google Spreadsheets.")
    parser.add_argument(
        "--type",
        choices=("clients", "deals", "tasks", "all"),
        default="all",
        dest="report_type",
    )
    return parser.parse_args(argv)


def _print_result(result: ReportExportResult) -> None:
    print(f"Report: {result.report_type.capitalize()}")
    print(f"Records: {result.records_count}")
    print(f"URL: {result.web_view_link}")


def _print_error(error: Exception) -> None:
    for error_type, prefix, hint in _ERROR_PRESENTATION:
        if isinstance(error, error_type):
            break
    else:
        prefix, hint = "Report export failed", None

    print(f"{prefix}: {error}", file=sys.stderr)
    if hint:
        print(f"Hint: {hint}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Only expected project/operational errors are reported as messages; anything
    # else is a bug and keeps its traceback.
    try:
        exporter = ReportExporter.from_env()

        export_sequence = {
            "clients": [exporter.export_clients_report],
            "deals": [exporter.export_deals_report],
            "tasks": [exporter.export_tasks_report],
            "all": [
                exporter.export_clients_report,
                exporter.export_deals_report,
                exporter.export_tasks_report,
            ],
        }[args.report_type]

        reports_created = 0
        for export_method in export_sequence:
            result = export_method()
            _print_result(result)
            reports_created += 1
        print(f"Reports created: {reports_created}")
    except EXPECTED_EXPORT_ERRORS as error:
        _print_error(error)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
