from __future__ import annotations

import argparse
import sys

from reports import ReportExportError, ReportExportResult, ReportExporter


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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
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
    try:
        for export_method in export_sequence:
            result = export_method()
            _print_result(result)
            reports_created += 1
        print(f"Reports created: {reports_created}")
    except ReportExportError as error:
        print(f"Report export failed: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
