from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from google.auth.exceptions import RefreshError
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from google_integration._transport import TRANSPORT_ERRORS, describe_transport_error
from google_integration.config import ConfigError, GoogleSheetsConfig

_INVALID_CREDENTIALS_MESSAGE = (
    "Google service account credentials file is invalid or malformed. "
    "Check GOOGLE_SERVICE_ACCOUNT_PATH."
)


class GoogleSheetsError(RuntimeError):
    """Base exception for Google Sheets client errors."""


class GoogleSheetsValidationError(GoogleSheetsError):
    """Raised when provided client arguments are invalid."""


class GoogleSheetsAPIError(GoogleSheetsError):
    """Raised when a Google Sheets API request fails."""


class SheetNotFoundError(GoogleSheetsError):
    """Raised when a sheet with the requested name does not exist."""


class SheetAlreadyExistsError(GoogleSheetsError):
    """Raised when attempting to create a duplicate sheet."""


class GoogleSheetsClient:
    DEFAULT_SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)
    SPREADSHEET_METADATA_FIELDS = "sheets(properties(sheetId,title,gridProperties))"

    def __init__(
        self,
        spreadsheet_id: str,
        credentials_path: str | Path,
        scopes: Sequence[str] | None = None,
        service: Any | None = None,
        service_builder: Any = build,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.credentials_path = Path(credentials_path)
        self.scopes = tuple(scopes or self.DEFAULT_SCOPES)
        self._service = service
        self._service_builder = service_builder

    @classmethod
    def from_config(
        cls,
        spreadsheet_id: str,
        config: GoogleSheetsConfig,
        scopes: Sequence[str] | None = None,
    ) -> "GoogleSheetsClient":
        return cls(
            spreadsheet_id=spreadsheet_id,
            credentials_path=config.credentials_path,
            scopes=scopes,
        )

    def _load_credentials(self) -> Credentials:
        # The one place the configured key file's content is parsed. google-auth
        # reports a bad file as a ValueError: JSONDecodeError / UnicodeDecodeError (not
        # JSON, not UTF-8), MalformedError (missing fields), InvalidValue (private_key
        # of the wrong type) and a bare ValueError for an unparseable private key.
        # Valid JSON that is not an object is the exception: it escapes as a bare
        # AttributeError from data.keys(), so it is checked up front rather than
        # catching AttributeError. Anything else, I/O errors included, says nothing
        # about the file's content and propagates unchanged. str(error) can embed file
        # content, so it is only kept as the cause.
        try:
            self._require_json_object()
            return Credentials.from_service_account_file(
                str(self.credentials_path),
                scopes=list(self.scopes),
            )
        except ValueError as error:
            raise ConfigError(_INVALID_CREDENTIALS_MESSAGE) from error

    def _require_json_object(self) -> None:
        with self.credentials_path.open(encoding="utf-8") as credentials_file:
            if not isinstance(json.load(credentials_file), dict):
                raise ValueError("Service account credentials must be a JSON object.")

    def _get_service(self) -> Any:
        if self._service is None:
            credentials = self._load_credentials()
            self._service = self._service_builder(
                "sheets",
                "v4",
                credentials=credentials,
                cache_discovery=False,
            )
        return self._service

    def _spreadsheets_resource(self) -> Any:
        return self._get_service().spreadsheets()

    def _values_resource(self) -> Any:
        return self._spreadsheets_resource().values()

    def _execute(self, request: Any, action: str) -> Any:
        try:
            return request.execute()
        except HttpError as error:
            status_code = getattr(error.resp, "status", "unknown")
            raise GoogleSheetsAPIError(
                f"Google Sheets API request failed while {action}. "
                f"HTTP status: {status_code}."
            ) from error
        except TRANSPORT_ERRORS as error:
            raise GoogleSheetsAPIError(
                f"Google Sheets API request failed while {action}. "
                f"Network error: {describe_transport_error(error)}."
            ) from error
        except RefreshError as error:
            # The service-account token is fetched inside the first execute(). str(error)
            # embeds the raw token-endpoint response, so it is only kept as the cause.
            raise GoogleSheetsAPIError(
                f"Google Sheets API request failed while {action}. "
                "Authentication error: Google service account credentials could not be refreshed."
            ) from error

    def _get_spreadsheet_metadata(self) -> dict[str, Any]:
        request = self._spreadsheets_resource().get(
            spreadsheetId=self.spreadsheet_id,
            includeGridData=False,
            fields=self.SPREADSHEET_METADATA_FIELDS,
        )
        return self._execute(request, "fetching spreadsheet metadata")

    def _validate_sheet_name(self, sheet_name: str) -> None:
        if not sheet_name or not sheet_name.strip():
            raise GoogleSheetsValidationError("Sheet name must not be empty.")

    def _validate_range_name(self, range_name: str) -> None:
        if not range_name or not range_name.strip():
            raise GoogleSheetsValidationError("Range name must not be empty.")

    def _normalize_values(self, values: Sequence[Sequence[Any]]) -> list[list[Any]]:
        if isinstance(values, (str, bytes)):
            raise GoogleSheetsValidationError("Values must be a two-dimensional array.")

        normalized_values: list[list[Any]] = []
        for row in values:
            if isinstance(row, (str, bytes)):
                raise GoogleSheetsValidationError("Each row must be a sequence of cell values.")
            normalized_values.append(list(row))
        return normalized_values

    def _validate_index_range(self, start: int, end: int, label: str) -> None:
        if start < 0 or end < 0:
            raise GoogleSheetsValidationError(
                f"{label.capitalize()} indexes must be zero-based and non-negative."
            )
        if end <= start:
            raise GoogleSheetsValidationError(
                f"{label.capitalize()} end index must be greater than start index."
            )

    def _get_sheet_properties(self, sheet_name: str) -> dict[str, Any]:
        self._validate_sheet_name(sheet_name)
        metadata = self._get_spreadsheet_metadata()

        for sheet in metadata.get("sheets", []):
            properties = sheet.get("properties", {})
            if properties.get("title") == sheet_name:
                return properties

        raise SheetNotFoundError(f"Sheet '{sheet_name}' was not found.")

    def _build_grid_range(
        self,
        sheet_name: str,
        start_row: int,
        end_row: int,
        start_column: int,
        end_column: int,
    ) -> dict[str, int]:
        """Build a GridRange using zero-based, end-exclusive indexes."""
        self._validate_index_range(start_row, end_row, "row")
        self._validate_index_range(start_column, end_column, "column")

        return {
            "sheetId": self.get_sheet_id(sheet_name),
            "startRowIndex": start_row,
            "endRowIndex": end_row,
            "startColumnIndex": start_column,
            "endColumnIndex": end_column,
        }

    def _batch_update(self, requests: list[dict[str, Any]], action: str) -> dict[str, Any]:
        request = self._spreadsheets_resource().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"requests": requests},
        )
        return self._execute(request, action)

    def get_sheet_names(self) -> list[str]:
        metadata = self._get_spreadsheet_metadata()
        sheets = metadata.get("sheets", [])
        return [
            sheet.get("properties", {}).get("title", "")
            for sheet in sheets
            if sheet.get("properties", {}).get("title")
        ]

    def get_sheet_id(self, sheet_name: str) -> int:
        properties = self._get_sheet_properties(sheet_name)
        sheet_id = properties.get("sheetId")
        if sheet_id is None:
            raise GoogleSheetsAPIError(
                f"Sheet '{sheet_name}' does not expose a valid sheetId."
            )
        return int(sheet_id)

    def read_range(self, range_name: str) -> list[list[Any]]:
        self._validate_range_name(range_name)
        request = self._values_resource().get(
            spreadsheetId=self.spreadsheet_id,
            range=range_name,
        )
        response = self._execute(request, f"reading range '{range_name}'")
        return response.get("values", [])

    def read_all_values(self, sheet_name: str) -> list[list[Any]]:
        return self.read_range(self._format_sheet_range(sheet_name))

    def create_sheet(self, sheet_name: str) -> int:
        self._validate_sheet_name(sheet_name)
        if sheet_name in self.get_sheet_names():
            raise SheetAlreadyExistsError(f"Sheet '{sheet_name}' already exists.")

        response = self._batch_update(
            requests=[{"addSheet": {"properties": {"title": sheet_name}}}],
            action=f"creating sheet '{sheet_name}'",
        )
        replies = response.get("replies", [])
        sheet_id = (
            replies[0]
            .get("addSheet", {})
            .get("properties", {})
            .get("sheetId")
            if replies
            else None
        )
        if sheet_id is None:
            raise GoogleSheetsAPIError(
                f"Google Sheets API did not return sheetId for sheet '{sheet_name}'."
            )
        return int(sheet_id)

    def delete_sheet(self, sheet_name: str) -> dict[str, Any]:
        return self._batch_update(
            requests=[{"deleteSheet": {"sheetId": self.get_sheet_id(sheet_name)}}],
            action=f"deleting sheet '{sheet_name}'",
        )

    def write_range(
        self, range_name: str, values: Sequence[Sequence[Any]]
    ) -> dict[str, Any]:
        self._validate_range_name(range_name)
        request = self._values_resource().update(
            spreadsheetId=self.spreadsheet_id,
            range=range_name,
            valueInputOption="RAW",
            body={"values": self._normalize_values(values)},
        )
        return self._execute(request, f"writing range '{range_name}'")

    def append_rows(
        self, range_name: str, values: Sequence[Sequence[Any]]
    ) -> dict[str, Any]:
        self._validate_range_name(range_name)
        request = self._values_resource().append(
            spreadsheetId=self.spreadsheet_id,
            range=range_name,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": self._normalize_values(values)},
        )
        return self._execute(request, f"appending rows to range '{range_name}'")

    def clear_range(self, range_name: str) -> dict[str, Any]:
        self._validate_range_name(range_name)
        request = self._values_resource().clear(
            spreadsheetId=self.spreadsheet_id,
            range=range_name,
            body={},
        )
        return self._execute(request, f"clearing range '{range_name}'")

    def format_range(
        self,
        sheet_name: str,
        start_row: int,
        end_row: int,
        start_column: int,
        end_column: int,
        *,
        background_color: dict[str, float] | None = None,
        bold: bool | None = None,
        font_size: int | None = None,
        horizontal_alignment: str | None = None,
        vertical_alignment: str | None = None,
        wrap_strategy: str | None = None,
        number_format: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Format a range using zero-based, end-exclusive GridRange indexes."""
        user_entered_format: dict[str, Any] = {}
        fields: list[str] = []

        if background_color is not None:
            user_entered_format["backgroundColor"] = background_color
            fields.append("userEnteredFormat.backgroundColor")

        text_format: dict[str, Any] = {}
        if bold is not None:
            text_format["bold"] = bold
            fields.append("userEnteredFormat.textFormat.bold")
        if font_size is not None:
            text_format["fontSize"] = font_size
            fields.append("userEnteredFormat.textFormat.fontSize")
        if text_format:
            user_entered_format["textFormat"] = text_format

        if horizontal_alignment is not None:
            user_entered_format["horizontalAlignment"] = horizontal_alignment
            fields.append("userEnteredFormat.horizontalAlignment")

        if vertical_alignment is not None:
            user_entered_format["verticalAlignment"] = vertical_alignment
            fields.append("userEnteredFormat.verticalAlignment")

        if wrap_strategy is not None:
            user_entered_format["wrapStrategy"] = wrap_strategy
            fields.append("userEnteredFormat.wrapStrategy")

        if number_format is not None:
            user_entered_format["numberFormat"] = number_format
            fields.append("userEnteredFormat.numberFormat")

        if not fields:
            raise GoogleSheetsValidationError(
                "At least one formatting property must be provided."
            )

        return self._batch_update(
            requests=[
                {
                    "repeatCell": {
                        "range": self._build_grid_range(
                            sheet_name,
                            start_row,
                            end_row,
                            start_column,
                            end_column,
                        ),
                        "cell": {"userEnteredFormat": user_entered_format},
                        "fields": ",".join(fields),
                    }
                }
            ],
            action=f"formatting range on sheet '{sheet_name}'",
        )

    def merge_cells(
        self,
        sheet_name: str,
        start_row: int,
        end_row: int,
        start_column: int,
        end_column: int,
    ) -> dict[str, Any]:
        """Merge cells using zero-based, end-exclusive GridRange indexes."""
        return self._batch_update(
            requests=[
                {
                    "mergeCells": {
                        "range": self._build_grid_range(
                            sheet_name,
                            start_row,
                            end_row,
                            start_column,
                            end_column,
                        ),
                        "mergeType": "MERGE_ALL",
                    }
                }
            ],
            action=f"merging cells on sheet '{sheet_name}'",
        )

    def unmerge_cells(
        self,
        sheet_name: str,
        start_row: int,
        end_row: int,
        start_column: int,
        end_column: int,
    ) -> dict[str, Any]:
        """Unmerge cells using zero-based, end-exclusive GridRange indexes."""
        return self._batch_update(
            requests=[
                {
                    "unmergeCells": {
                        "range": self._build_grid_range(
                            sheet_name,
                            start_row,
                            end_row,
                            start_column,
                            end_column,
                        )
                    }
                }
            ],
            action=f"unmerging cells on sheet '{sheet_name}'",
        )

    def set_column_width(
        self,
        sheet_name: str,
        start_column: int,
        end_column: int,
        width_pixels: int,
    ) -> dict[str, Any]:
        if width_pixels <= 0:
            raise GoogleSheetsValidationError("Column width must be greater than zero.")
        self._validate_index_range(start_column, end_column, "column")

        return self._batch_update(
            requests=[
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": self.get_sheet_id(sheet_name),
                            "dimension": "COLUMNS",
                            "startIndex": start_column,
                            "endIndex": end_column,
                        },
                        "properties": {"pixelSize": width_pixels},
                        "fields": "pixelSize",
                    }
                }
            ],
            action=f"setting column width on sheet '{sheet_name}'",
        )

    def set_row_height(
        self,
        sheet_name: str,
        start_row: int,
        end_row: int,
        height_pixels: int,
    ) -> dict[str, Any]:
        if height_pixels <= 0:
            raise GoogleSheetsValidationError("Row height must be greater than zero.")
        self._validate_index_range(start_row, end_row, "row")

        return self._batch_update(
            requests=[
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": self.get_sheet_id(sheet_name),
                            "dimension": "ROWS",
                            "startIndex": start_row,
                            "endIndex": end_row,
                        },
                        "properties": {"pixelSize": height_pixels},
                        "fields": "pixelSize",
                    }
                }
            ],
            action=f"setting row height on sheet '{sheet_name}'",
        )

    def freeze_rows(self, sheet_name: str, row_count: int) -> dict[str, Any]:
        if row_count < 0:
            raise GoogleSheetsValidationError("Frozen row count must not be negative.")

        return self._batch_update(
            requests=[
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": self.get_sheet_id(sheet_name),
                            "gridProperties": {"frozenRowCount": row_count},
                        },
                        "fields": "gridProperties.frozenRowCount",
                    }
                }
            ],
            action=f"freezing rows on sheet '{sheet_name}'",
        )

    @staticmethod
    def _format_sheet_range(sheet_name: str) -> str:
        escaped_name = sheet_name.replace("'", "''")
        return f"'{escaped_name}'"
