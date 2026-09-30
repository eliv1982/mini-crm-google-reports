from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Sequence

from google_integration import (
    ConfigError,
    GoogleDriveClient,
    GoogleDriveError,
    GoogleSheetsClient,
    GoogleSheetsError,
    load_google_drive_config,
    load_google_sheets_config,
)

from .analytics import (
    compute_clients_analytics,
    compute_deals_analytics,
    compute_tasks_analytics,
)
from .api_client import CRMAPIClient, CRMAPIError


class ReportExportError(RuntimeError):
    """Raised when a CRM report cannot be exported successfully."""


# Project exceptions that describe expected operational failures (configuration,
# backend connectivity, Google APIs). Entry points show their messages to the user;
# any other exception is treated as an unexpected bug.
EXPECTED_EXPORT_ERRORS = (
    ConfigError,
    CRMAPIError,
    GoogleDriveError,
    GoogleSheetsError,
    ReportExportError,
)


@dataclass(frozen=True)
class ReportExportResult:
    report_type: str
    spreadsheet_id: str
    name: str
    web_view_link: str
    records_count: int


@dataclass(frozen=True)
class _ReportLayout:
    summary_label_start_row: int
    summary_label_end_row: int
    table_header_row: int
    first_data_row: int
    total_rows: int
    total_columns: int


class ReportExporter:
    def __init__(
        self,
        api_client: CRMAPIClient,
        drive_client: GoogleDriveClient,
        sheets_client_factory: Callable[[str], GoogleSheetsClient],
        *,
        drive_folder_id: str,
        time_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.api_client = api_client
        self.drive_client = drive_client
        self.sheets_client_factory = sheets_client_factory
        self.drive_folder_id = drive_folder_id.strip()
        self.time_provider = time_provider or datetime.now

        if not self.drive_folder_id:
            raise ReportExportError("GOOGLE_DRIVE_FOLDER_ID must not be empty.")

    @classmethod
    def from_env(cls) -> "ReportExporter":
        drive_config = load_google_drive_config()
        sheets_config = load_google_sheets_config()
        if not drive_config.drive_folder_id:
            raise ReportExportError("GOOGLE_DRIVE_FOLDER_ID must be set before exporting reports.")

        drive_client = GoogleDriveClient.from_config(drive_config)

        def sheets_client_factory(spreadsheet_id: str) -> GoogleSheetsClient:
            return GoogleSheetsClient.from_config(spreadsheet_id, sheets_config)

        return cls(
            api_client=CRMAPIClient(),
            drive_client=drive_client,
            sheets_client_factory=sheets_client_factory,
            drive_folder_id=drive_config.drive_folder_id,
        )

    def export_clients_report(self) -> ReportExportResult:
        self.api_client.check_health()
        clients = self.api_client.get_all_clients()
        analytics = compute_clients_analytics(clients)

        summary_rows = [
            ("Total clients", analytics["total_clients"]),
            ("Active clients", analytics["active_clients"]),
            ("Archived clients", analytics["archived_clients"]),
            ("Clients with company", analytics["clients_with_company"]),
            ("Clients without company", analytics["clients_without_company"]),
            (
                "Most common company",
                self._format_company_metric(analytics["most_common_company"]),
            ),
            ("Percentage active", round(analytics["percentage_active"], 2)),
        ]
        data_headers = [
            "ID",
            "Name",
            "Company",
            "Email",
            "Phone",
            "Status",
            "Created At",
            "Updated At",
        ]
        data_rows = [
            [
                client.get("id"),
                client.get("name"),
                client.get("company"),
                client.get("email"),
                client.get("phone"),
                client.get("status"),
                client.get("created_at"),
                client.get("updated_at"),
            ]
            for client in clients
        ]
        return self._export_report(
            report_type="clients",
            title_prefix="Mini CRM - Clients Report",
            summary_rows=summary_rows,
            data_headers=data_headers,
            data_rows=data_rows,
            column_widths=(90, 180, 200, 220, 140, 110, 170, 170),
            wrap_data_columns=(1, 2, 3, 4, 6, 7),
        )

    def export_deals_report(self) -> ReportExportResult:
        self.api_client.check_health()
        deals = self.api_client.get_all_deals()
        analytics = compute_deals_analytics(deals)

        summary_rows = [
            ("Total deals", analytics["total_deals"]),
            ("Total amount", analytics["total_amount"]),
            ("Average amount", analytics["average_amount"]),
            ("New deals", analytics["status_counts"]["new"]),
            ("In progress deals", analytics["status_counts"]["in_progress"]),
            ("Won deals", analytics["status_counts"]["won"]),
            ("Lost deals", analytics["status_counts"]["lost"]),
            ("Won amount", analytics["won_amount"]),
            ("Average won amount", analytics["average_won_amount"]),
            ("Deals with client", analytics["deals_with_client"]),
            ("Deals without client", analytics["deals_without_client"]),
        ]
        data_headers = [
            "ID",
            "Title",
            "Client ID",
            "Amount",
            "Status",
            "Expected Close Date",
            "Created At",
            "Updated At",
        ]
        data_rows = [
            [
                deal.get("id"),
                deal.get("title"),
                deal.get("client_id"),
                deal.get("amount"),
                deal.get("status"),
                deal.get("expected_close_date"),
                deal.get("created_at"),
                deal.get("updated_at"),
            ]
            for deal in deals
        ]
        return self._export_report(
            report_type="deals",
            title_prefix="Mini CRM - Deals Report",
            summary_rows=summary_rows,
            data_headers=data_headers,
            data_rows=data_rows,
            column_widths=(90, 260, 100, 120, 120, 150, 170, 170),
            wrap_data_columns=(1, 5, 6, 7),
            numeric_columns=(3,),
        )

    def export_tasks_report(self) -> ReportExportResult:
        self.api_client.check_health()
        tasks = self.api_client.get_all_tasks()
        analytics = compute_tasks_analytics(tasks)

        summary_rows = [
            ("Total tasks", analytics["total_tasks"]),
            ("Completed tasks", analytics["completed_tasks"]),
            ("Open tasks", analytics["open_tasks"]),
            ("Completion percentage", round(analytics["completion_percentage"], 2)),
            ("Overdue open tasks", analytics["overdue_open_tasks"]),
            ("Tasks with client", analytics["tasks_with_client"]),
            ("Tasks with deal", analytics["tasks_with_deal"]),
            ("Tasks without links", analytics["tasks_without_links"]),
        ]
        data_headers = [
            "ID",
            "Title",
            "Description",
            "Client ID",
            "Deal ID",
            "Due Date",
            "Completed",
            "Created At",
            "Updated At",
        ]
        data_rows = [
            [
                task.get("id"),
                task.get("title"),
                task.get("description"),
                task.get("client_id"),
                task.get("deal_id"),
                task.get("due_date"),
                task.get("completed"),
                task.get("created_at"),
                task.get("updated_at"),
            ]
            for task in tasks
        ]
        return self._export_report(
            report_type="tasks",
            title_prefix="Mini CRM - Tasks Report",
            summary_rows=summary_rows,
            data_headers=data_headers,
            data_rows=data_rows,
            column_widths=(90, 180, 320, 100, 100, 130, 110, 170, 170),
            wrap_data_columns=(1, 2, 7, 8),
        )

    def _export_report(
        self,
        *,
        report_type: str,
        title_prefix: str,
        summary_rows: Sequence[tuple[str, Any]],
        data_headers: Sequence[str],
        data_rows: Sequence[Sequence[Any]],
        column_widths: Sequence[int],
        wrap_data_columns: Sequence[int] = (),
        numeric_columns: Sequence[int] = (),
    ) -> ReportExportResult:
        report_name = f"{title_prefix} - {self.time_provider().strftime('%Y-%m-%d %H-%M')}"
        created_file = self.drive_client.create_google_spreadsheet(
            name=report_name,
            parent_folder_id=self.drive_folder_id,
        )
        spreadsheet_id = str(created_file["id"])
        web_view_link = str(created_file.get("webViewLink", ""))

        try:
            sheets_client = self.sheets_client_factory(spreadsheet_id)
            sheet_names = sheets_client.get_sheet_names()
            if not sheet_names:
                raise ReportExportError("Google Spreadsheet does not expose any sheets.")

            primary_sheet_name = sheet_names[0]
            rows, layout = self._build_report_rows(report_name, summary_rows, data_headers, data_rows)
            range_name = self._build_range_name(
                primary_sheet_name,
                start_cell="A1",
                end_cell=f"{self._column_letter(layout.total_columns)}{layout.total_rows}",
            )
            sheets_client.write_range(range_name, rows)
            self._format_report_sheet(
                sheets_client,
                primary_sheet_name,
                layout,
                len(data_headers),
                column_widths,
                wrap_data_columns,
                numeric_columns,
            )
        except Exception as exc:
            raise ReportExportError(
                f"Failed to export {report_type} report after spreadsheet creation. "
                f"Cause: {self._describe_failure(exc)}. "
                f"spreadsheet_id={spreadsheet_id}. "
                f"web_view_link={web_view_link or '<unavailable>'}."
            ) from exc

        return ReportExportResult(
            report_type=report_type,
            spreadsheet_id=spreadsheet_id,
            name=str(created_file.get("name", report_name)),
            web_view_link=web_view_link,
            records_count=len(data_rows),
        )

    def _format_report_sheet(
        self,
        sheets_client: GoogleSheetsClient,
        sheet_name: str,
        layout: _ReportLayout,
        total_data_columns: int,
        column_widths: Sequence[int],
        wrap_data_columns: Sequence[int],
        numeric_columns: Sequence[int],
    ) -> None:
        sheets_client.format_range(
            sheet_name,
            0,
            1,
            0,
            1,
            bold=True,
            font_size=14,
        )
        sheets_client.format_range(
            sheet_name,
            2,
            3,
            0,
            2,
            bold=True,
            background_color={"red": 0.91, "green": 0.95, "blue": 1.0},
        )
        if layout.summary_label_start_row < layout.summary_label_end_row:
            sheets_client.format_range(
                sheet_name,
                layout.summary_label_start_row,
                layout.summary_label_end_row,
                0,
                1,
                bold=True,
            )
        sheets_client.format_range(
            sheet_name,
            layout.table_header_row,
            layout.table_header_row + 1,
            0,
            total_data_columns,
            bold=True,
            background_color={"red": 0.86, "green": 0.91, "blue": 0.98},
            wrap_strategy="WRAP",
        )
        sheets_client.freeze_rows(sheet_name, layout.table_header_row + 1)

        for column_index, width in enumerate(column_widths):
            sheets_client.set_column_width(sheet_name, column_index, column_index + 1, width)

        if layout.first_data_row < layout.total_rows:
            for column_index in wrap_data_columns:
                sheets_client.format_range(
                    sheet_name,
                    layout.first_data_row,
                    layout.total_rows,
                    column_index,
                    column_index + 1,
                    wrap_strategy="WRAP",
                    vertical_alignment="TOP",
                )

            for column_index in numeric_columns:
                sheets_client.format_range(
                    sheet_name,
                    layout.first_data_row,
                    layout.total_rows,
                    column_index,
                    column_index + 1,
                    number_format={"type": "NUMBER", "pattern": "#,##0.00"},
                )

    def _build_report_rows(
        self,
        report_name: str,
        summary_rows: Sequence[tuple[str, Any]],
        data_headers: Sequence[str],
        data_rows: Sequence[Sequence[Any]],
    ) -> tuple[list[list[Any]], _ReportLayout]:
        rows: list[list[Any]] = [[report_name], [], ["SUMMARY / KEY METRICS"]]
        rows.extend([[label, value] for label, value in summary_rows])
        rows.append([])
        table_header_row = len(rows)
        rows.append(list(data_headers))
        first_data_row = len(rows)
        rows.extend([list(row) for row in data_rows])

        layout = _ReportLayout(
            summary_label_start_row=3,
            summary_label_end_row=3 + len(summary_rows),
            table_header_row=table_header_row,
            first_data_row=first_data_row,
            total_rows=len(rows),
            total_columns=max(len(data_headers), 2),
        )
        return rows, layout

    @staticmethod
    def _describe_failure(exc: Exception) -> str:
        # Only project exceptions carry messages written to be shown to users;
        # for anything else expose just the type and rely on exception chaining.
        if isinstance(exc, EXPECTED_EXPORT_ERRORS):
            return str(exc).rstrip(".")
        return f"unexpected {type(exc).__name__}"

    @staticmethod
    def _build_range_name(sheet_name: str, start_cell: str, end_cell: str) -> str:
        escaped_sheet_name = sheet_name.replace("'", "''")
        return f"'{escaped_sheet_name}'!{start_cell}:{end_cell}"

    @staticmethod
    def _column_letter(column_number: int) -> str:
        if column_number <= 0:
            raise ValueError("Column number must be positive.")
        result = ""
        current = column_number
        while current > 0:
            current, remainder = divmod(current - 1, 26)
            result = chr(65 + remainder) + result
        return result

    @staticmethod
    def _format_company_metric(metric: dict[str, Any]) -> str:
        company = metric.get("company")
        count = metric.get("count", 0)
        if company:
            return f"{company} ({count})"
        return "N/A (0)"
