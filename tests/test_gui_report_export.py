from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httplib2
import pytest

from google_integration import (
    ConfigError,
    GoogleDriveClient,
    GoogleDriveOperationError,
    GoogleSheetsAPIError,
    GoogleSheetsClient,
)
from gui import app as gui_app
from gui.app import GUIValidationError, MiniCRMApp
from reports import CRMAPIError, ReportExportError, ReportExporter, ReportExportResult
from tests.auth_failures import (
    DRIVE_AUTH_FAILURES,
    DRIVE_AUTH_REASON,
    RAW_AUTH_DETAIL,
    drive_client_failing_auth,
)
from tests.credential_files import (
    DRIVE_AUTHENTICATION_MESSAGE,
    MALFORMED_SERVICE_ACCOUNT_FILES,
    RAW_SECRET,
    SHEETS_INVALID_CREDENTIALS_MESSAGE,
    write_credential_file,
)
from tests.transport_failures import RAW_DETAIL, drive_client_failing_with


class FakeRoot:
    """Stands in for Tk's event queue: `after` callbacks only run when the test drains them."""

    def __init__(self) -> None:
        self.scheduled = []

    def after(self, _delay_ms, callback) -> None:
        self.scheduled.append(callback)

    def run_scheduled(self) -> None:
        while self.scheduled:
            self.scheduled.pop(0)()


class FakeButton:
    def __init__(self) -> None:
        self.state = "normal"

    def configure(self, *, state: str) -> None:
        self.state = state


class ImmediateThread:
    def __init__(self, *, target, daemon=None) -> None:
        self._target = target

    def start(self) -> None:
        self._target()


@pytest.fixture
def gui(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    app = MiniCRMApp.__new__(MiniCRMApp)  # avoid building real Tk widgets
    app.root = FakeRoot()
    showerror = Mock()
    result_dialog = Mock()
    monkeypatch.setattr(gui_app, "messagebox", SimpleNamespace(showerror=showerror))
    monkeypatch.setattr(gui_app, "threading", SimpleNamespace(Thread=ImmediateThread))
    monkeypatch.setattr(gui_app, "ReportResultDialog", result_dialog)
    return SimpleNamespace(app=app, showerror=showerror, result_dialog=result_dialog)


def _export(gui: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, outcome) -> FakeButton:
    def fake_dispatch(report_type: str):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(gui_app, "dispatch_report_export", fake_dispatch)
    button = FakeButton()

    gui.app.start_report_export("clients", button)

    # The worker thread has finished; the UI must only be touched via root.after.
    assert button.state == "disabled"
    gui.showerror.assert_not_called()
    gui.result_dialog.assert_not_called()

    gui.app.root.run_scheduled()
    return button


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(ConfigError("Google OAuth client secret file was not found. Check GOOGLE_OAUTH_CLIENT_SECRET_PATH."), id="config"),
        pytest.param(CRMAPIError("CRM API health check failed: could not connect to http://localhost:8000"), id="backend"),
        pytest.param(GoogleDriveOperationError("Google Drive API request failed while creating spreadsheet. HTTP status: 404."), id="drive"),
        pytest.param(GoogleSheetsAPIError("Google Sheets API request failed while writing range. HTTP status: 403."), id="sheets"),
        pytest.param(ReportExportError("Failed to export clients report after spreadsheet creation. spreadsheet_id=abc."), id="report-export"),
        pytest.param(GUIValidationError("Unsupported report type: nope"), id="gui-validation"),
    ],
)
def test_known_export_error_shows_project_message_and_restores_button(
    gui: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    button = _export(gui, monkeypatch, error)

    gui.showerror.assert_called_once()
    title, message = gui.showerror.call_args.args
    assert title == gui_app.WINDOW_TITLE
    assert message.startswith("Report export failed.")
    assert str(error) in message
    assert "Traceback" not in message
    gui.result_dialog.assert_not_called()
    assert button.state == "normal"


def _export_with_real_drive_client(
    gui: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, drive_client
) -> tuple[FakeButton, ReportExporter]:
    # Real dispatch, exporter, Drive client and googleapiclient execute(); only what
    # sits underneath the Drive client (transport or token refresh) is simulated.
    exporter = ReportExporter(
        api_client=Mock(get_all_clients=Mock(return_value=[])),
        drive_client=drive_client,
        sheets_client_factory=Mock(),
        drive_folder_id="folder-1",
        time_provider=lambda: datetime(2026, 7, 17, 12, 45),
    )
    real_dispatch = gui_app.dispatch_report_export
    monkeypatch.setattr(
        gui_app,
        "dispatch_report_export",
        lambda report_type: real_dispatch(report_type, exporter_factory=lambda: exporter),
    )
    button = FakeButton()

    gui.app.start_report_export("clients", button)
    assert button.state == "disabled"
    gui.showerror.assert_not_called()
    gui.app.root.run_scheduled()
    return button, exporter


@pytest.mark.parametrize("make_failure", DRIVE_AUTH_FAILURES)
def test_drive_auth_failure_shows_project_message_and_restores_button(
    gui: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    make_failure,
) -> None:
    drive_client, _ = drive_client_failing_auth(make_failure)

    button, exporter = _export_with_real_drive_client(gui, monkeypatch, drive_client)

    gui.showerror.assert_called_once()
    title, message = gui.showerror.call_args.args
    assert title == gui_app.WINDOW_TITLE
    assert message.startswith("Report export failed.")
    assert "Google Drive API request failed while creating spreadsheet" in message
    assert DRIVE_AUTH_REASON in message
    assert RAW_AUTH_DETAIL not in message
    assert "invalid_grant" not in message
    assert "Traceback" not in message
    assert "Unexpected report export error" not in capsys.readouterr().err
    gui.result_dialog.assert_not_called()
    exporter.sheets_client_factory.assert_not_called()
    assert button.state == "normal"


def test_drive_transport_failure_shows_project_message_and_restores_button(
    gui: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    drive_client, _ = drive_client_failing_with(httplib2.ServerNotFoundError(RAW_DETAIL))

    button, exporter = _export_with_real_drive_client(gui, monkeypatch, drive_client)

    gui.showerror.assert_called_once()
    title, message = gui.showerror.call_args.args
    assert title == gui_app.WINDOW_TITLE
    assert message.startswith("Report export failed.")
    assert "Google Drive API request failed while creating spreadsheet" in message
    assert "Network error: could not connect to Google" in message
    assert RAW_DETAIL not in message
    assert "Traceback" not in message
    assert "Unexpected report export error" not in capsys.readouterr().err
    gui.result_dialog.assert_not_called()
    exporter.sheets_client_factory.assert_not_called()
    assert button.state == "normal"


@pytest.mark.parametrize("content", MALFORMED_SERVICE_ACCOUNT_FILES)
def test_malformed_service_account_file_shows_project_message_and_restores_button(
    gui: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    content,
) -> None:
    # Real dispatch, exporter and Sheets client; the key file is parsed after Drive
    # has created the spreadsheet.
    credentials_path = write_credential_file(tmp_path, content)
    drive_client = Mock()
    drive_client.create_google_spreadsheet.return_value = {
        "id": "sheet-42",
        "name": "Report",
        "webViewLink": "https://docs.test/sheet-42",
    }
    exporter = ReportExporter(
        api_client=Mock(get_all_clients=Mock(return_value=[])),
        drive_client=drive_client,
        sheets_client_factory=lambda spreadsheet_id: GoogleSheetsClient(
            spreadsheet_id=spreadsheet_id,
            credentials_path=credentials_path,
            service_builder=Mock(),
        ),
        drive_folder_id="folder-1",
        time_provider=lambda: datetime(2026, 7, 17, 12, 45),
    )
    real_dispatch = gui_app.dispatch_report_export
    monkeypatch.setattr(
        gui_app,
        "dispatch_report_export",
        lambda report_type: real_dispatch(report_type, exporter_factory=lambda: exporter),
    )
    button = FakeButton()

    gui.app.start_report_export("clients", button)
    assert button.state == "disabled"
    gui.showerror.assert_not_called()
    gui.app.root.run_scheduled()

    gui.showerror.assert_called_once()
    title, message = gui.showerror.call_args.args
    assert title == gui_app.WINDOW_TITLE
    assert message.startswith("Report export failed.")
    assert SHEETS_INVALID_CREDENTIALS_MESSAGE.rstrip(".") in message
    assert "unexpected" not in message
    assert "spreadsheet_id=sheet-42" in message
    assert RAW_SECRET not in message
    assert str(credentials_path) not in message
    assert "Traceback" not in message
    assert "Unexpected report export error" not in capsys.readouterr().err
    gui.result_dialog.assert_not_called()
    assert button.state == "normal"


@pytest.mark.parametrize(
    ("kind", "content"),
    [
        pytest.param("client_secret", "null", id="client-secret-json-null"),
        pytest.param("token", "[1]", id="token-json-list"),
        pytest.param("client_secret", "{not json", id="client-secret-invalid-json"),
    ],
)
def test_malformed_drive_credential_file_shows_project_message_and_restores_button(
    gui: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    kind: str,
    content: str,
) -> None:
    bad_path = write_credential_file(tmp_path, content, f"{kind}.json")
    missing_path = tmp_path / "missing.json"
    drive_client = GoogleDriveClient(
        client_secret_path=bad_path if kind == "client_secret" else missing_path,
        token_path=bad_path if kind == "token" else missing_path,
    )

    button, exporter = _export_with_real_drive_client(gui, monkeypatch, drive_client)

    gui.showerror.assert_called_once()
    title, message = gui.showerror.call_args.args
    assert title == gui_app.WINDOW_TITLE
    assert message == f"Report export failed.\n\n{DRIVE_AUTHENTICATION_MESSAGE}"
    assert RAW_SECRET not in message
    assert str(bad_path) not in message
    assert "Unexpected report export error" not in capsys.readouterr().err
    gui.result_dialog.assert_not_called()
    exporter.sheets_client_factory.assert_not_called()
    assert button.state == "normal"


def test_unexpected_export_error_stays_generic_and_restores_button(
    gui: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    button = _export(gui, monkeypatch, KeyError("internal-secret-detail"))

    gui.showerror.assert_called_once_with(gui_app.WINDOW_TITLE, "Report export failed.")
    assert "internal-secret-detail" not in gui.showerror.call_args.args[1]
    assert "Unexpected report export error" in capsys.readouterr().err
    assert button.state == "normal"


def test_successful_export_opens_result_dialog_and_restores_button(
    gui: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = ReportExportResult("clients", "id-1", "Clients report", "https://docs.test/1", 7)

    button = _export(gui, monkeypatch, result)

    gui.showerror.assert_not_called()
    gui.result_dialog.assert_called_once()
    dialog_kwargs = gui.result_dialog.call_args.kwargs
    assert dialog_kwargs["report_name"] == "Clients report"
    assert dialog_kwargs["records_count"] == 7
    assert dialog_kwargs["url"] == "https://docs.test/1"
    assert button.state == "normal"
