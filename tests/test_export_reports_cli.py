from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from google_integration import (
    ConfigError,
    GoogleDriveAuthenticationError,
    GoogleDriveClient,
    GoogleDriveOperationError,
    GoogleSheetsAPIError,
    GoogleSheetsClient,
    SheetNotFoundError,
)
from reports import (
    CRMAPIClient,
    CRMAPIError,
    ReportExportError,
    ReportExportResult,
    ReportExporter,
)
from scripts import export_reports
from tests.auth_failures import (
    DRIVE_AUTH_FAILURES,
    DRIVE_AUTH_REASON,
    RAW_AUTH_DETAIL,
    SHEETS_AUTH_FAILURES,
    SHEETS_AUTH_REASON,
    drive_client_failing_auth,
    sheets_client_failing_auth,
)
from tests.credential_files import (
    DRIVE_AUTHENTICATION_MESSAGE,
    MALFORMED_SERVICE_ACCOUNT_FILES,
    RAW_SECRET,
    SHEETS_INVALID_CREDENTIALS_MESSAGE,
    write_credential_file,
)
from tests.transport_failures import RAW_DETAIL, TRANSPORT_FAILURES, drive_client_failing_with

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# (raised error, expected message prefix, expected hint fragment)
KNOWN_FAILURES = [
    pytest.param(
        ConfigError("Google service account file was not found. Check GOOGLE_SERVICE_ACCOUNT_PATH."),
        "Configuration error: Google service account file was not found",
        ".env",
        id="config",
    ),
    pytest.param(
        CRMAPIError("CRM API health check failed: could not connect to http://localhost:8000"),
        "Backend error: CRM API health check failed: could not connect to http://localhost:8000",
        "backend is running",
        id="backend-unavailable",
    ),
    pytest.param(
        CRMAPIError("Failed to fetch /clients at offset 0: HTTP 500: {}"),
        "Backend error: Failed to fetch /clients at offset 0: HTTP 500",
        "backend is running",
        id="backend-http-error",
    ),
    pytest.param(
        GoogleDriveAuthenticationError("Failed to authenticate with Google Drive OAuth."),
        "Google Drive error: Failed to authenticate with Google Drive OAuth.",
        "GOOGLE_DRIVE_FOLDER_ID",
        id="drive-auth",
    ),
    pytest.param(
        GoogleDriveOperationError("Google Drive API request failed while creating spreadsheet. HTTP status: 404."),
        "Google Drive error: Google Drive API request failed while creating spreadsheet. HTTP status: 404.",
        "GOOGLE_DRIVE_FOLDER_ID",
        id="drive-operation",
    ),
    pytest.param(
        GoogleSheetsAPIError("Google Sheets API request failed while writing range. HTTP status: 403."),
        "Google Sheets error: Google Sheets API request failed while writing range. HTTP status: 403.",
        "GOOGLE_SERVICE_ACCOUNT_PATH",
        id="sheets-api",
    ),
    pytest.param(
        SheetNotFoundError("Sheet 'Sheet1' was not found."),
        "Google Sheets error: Sheet 'Sheet1' was not found.",
        "GOOGLE_SERVICE_ACCOUNT_PATH",
        id="sheets-not-found",
    ),
    pytest.param(
        ReportExportError("GOOGLE_DRIVE_FOLDER_ID must be set before exporting reports."),
        "Report export failed: GOOGLE_DRIVE_FOLDER_ID must be set before exporting reports.",
        None,
        id="report-export",
    ),
]


def _result(report_type: str) -> ReportExportResult:
    return ReportExportResult(report_type, "id", f"{report_type} report", f"https://{report_type}.test", 3)


def _fake_exporter(**methods) -> Mock:
    exporter = Mock()
    exporter.export_clients_report.return_value = _result("clients")
    exporter.export_deals_report.return_value = _result("deals")
    exporter.export_tasks_report.return_value = _result("tasks")
    for name, behavior in methods.items():
        getattr(exporter, name).side_effect = behavior
    return exporter


def _assert_clean_failure(captured, expected_stderr: str, hint: str | None) -> None:
    assert expected_stderr in captured.err
    if hint is not None:
        assert "Hint:" in captured.err and hint in captured.err
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out
    assert "Reports created" not in captured.out


@pytest.mark.parametrize(("error", "expected_stderr", "hint"), KNOWN_FAILURES)
def test_cli_reports_known_error_from_exporter_setup_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], error, expected_stderr, hint
) -> None:
    monkeypatch.setattr(ReportExporter, "from_env", Mock(side_effect=error))

    exit_code = export_reports.main(["--type", "clients"])

    assert exit_code == 1
    _assert_clean_failure(capsys.readouterr(), expected_stderr, hint)


@pytest.mark.parametrize(("error", "expected_stderr", "hint"), KNOWN_FAILURES)
def test_cli_reports_known_error_from_export_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], error, expected_stderr, hint
) -> None:
    exporter = _fake_exporter(export_clients_report=error)
    monkeypatch.setattr(ReportExporter, "from_env", Mock(return_value=exporter))

    exit_code = export_reports.main(["--type", "clients"])

    assert exit_code == 1
    _assert_clean_failure(capsys.readouterr(), expected_stderr, hint)


def test_cli_all_stops_at_first_failure_and_keeps_earlier_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    exporter = _fake_exporter(export_deals_report=GoogleSheetsAPIError("write failed"))
    monkeypatch.setattr(ReportExporter, "from_env", Mock(return_value=exporter))

    exit_code = export_reports.main(["--type", "all"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Report: Clients" in captured.out
    assert "Google Sheets error: write failed" in captured.err
    assert "Reports created" not in captured.out
    exporter.export_tasks_report.assert_not_called()


@pytest.mark.parametrize("stage", ["setup", "export"])
def test_cli_does_not_swallow_unexpected_errors(monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
    bug = TypeError("programming error")
    if stage == "setup":
        monkeypatch.setattr(ReportExporter, "from_env", Mock(side_effect=bug))
    else:
        monkeypatch.setattr(
            ReportExporter, "from_env", Mock(return_value=_fake_exporter(export_clients_report=bug))
        )

    with pytest.raises(TypeError, match="programming error"):
        export_reports.main(["--type", "clients"])


def test_cli_success_exits_zero(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(ReportExporter, "from_env", Mock(return_value=_fake_exporter()))

    exit_code = export_reports.main(["--type", "all"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Reports created: 3" in captured.out
    assert captured.err == ""


def _real_exporter(*, session=None, drive_client=None, sheets_client=None) -> ReportExporter:
    return ReportExporter(
        api_client=CRMAPIClient(base_url="http://api.test", session=session or Mock()),
        drive_client=drive_client or Mock(),
        sheets_client_factory=Mock(return_value=sheets_client or Mock()),
        drive_folder_id="folder-1",
        time_provider=lambda: datetime(2026, 7, 17, 12, 45),
    )


def test_cli_backend_down_is_reported_before_any_spreadsheet_is_created(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    session = Mock()
    session.request.side_effect = requests.ConnectionError("HTTPConnectionPool ... <urllib3 object at 0x1>")
    drive_client = Mock()
    exporter = _real_exporter(session=session, drive_client=drive_client)
    monkeypatch.setattr(ReportExporter, "from_env", Mock(return_value=exporter))

    exit_code = export_reports.main(["--type", "clients"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Backend error: CRM API health check failed: could not connect to http://api.test" in captured.err
    assert "urllib3" not in captured.err
    assert "Traceback" not in captured.err
    drive_client.create_google_spreadsheet.assert_not_called()


def test_cli_google_failure_after_creation_shows_cause_and_spreadsheet_link(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    session = Mock()
    session.request.side_effect = [
        Mock(status_code=200, json=Mock(return_value={"status": "ok"})),
        Mock(status_code=200, json=Mock(return_value=[])),
    ]
    drive_client = Mock()
    drive_client.create_google_spreadsheet.return_value = {
        "id": "sheet-42",
        "name": "Report",
        "webViewLink": "https://docs.test/sheet-42",
    }
    sheets_client = Mock()
    sheets_client.get_sheet_names.return_value = ["Sheet1"]
    sheets_client.write_range.side_effect = GoogleSheetsAPIError(
        "Google Sheets API request failed while writing range 'Sheet1'!A1:H9. HTTP status: 403."
    )
    exporter = _real_exporter(session=session, drive_client=drive_client, sheets_client=sheets_client)
    monkeypatch.setattr(ReportExporter, "from_env", Mock(return_value=exporter))

    exit_code = export_reports.main(["--type", "clients"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Report export failed:" in captured.err
    assert "HTTP status: 403" in captured.err
    assert "spreadsheet_id=sheet-42" in captured.err
    assert "web_view_link=https://docs.test/sheet-42" in captured.err
    assert "Traceback" not in captured.err
    drive_client.delete_file.assert_not_called()


def _healthy_backend_session() -> Mock:
    session = Mock()
    session.request.side_effect = [
        Mock(status_code=200, json=Mock(return_value={"status": "ok"})),
        Mock(status_code=200, json=Mock(return_value=[])),
    ]
    return session


@pytest.mark.parametrize(("make_error", "reason"), TRANSPORT_FAILURES)
def test_cli_drive_transport_failure_before_creation_prints_message_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], make_error, reason
) -> None:
    # The real Drive client and googleapiclient execute() path raise a raw transport error.
    drive_client, _ = drive_client_failing_with(make_error())
    exporter = _real_exporter(session=_healthy_backend_session(), drive_client=drive_client)
    monkeypatch.setattr(ReportExporter, "from_env", Mock(return_value=exporter))

    exit_code = export_reports.main(["--type", "clients"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert (
        "Google Drive error: Google Drive API request failed while creating spreadsheet "
        f"'Mini CRM - Clients Report - 2026-07-17 12-45'. Network error: {reason}."
    ) in captured.err
    assert RAW_DETAIL not in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""
    exporter.sheets_client_factory.assert_not_called()


@pytest.mark.parametrize("make_failure", DRIVE_AUTH_FAILURES)
def test_cli_drive_auth_failure_before_creation_prints_message_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], make_failure
) -> None:
    # Real credentials, AuthorizedHttp and execute(): the token refresh raises RefreshError.
    drive_client, _ = drive_client_failing_auth(make_failure)
    exporter = _real_exporter(session=_healthy_backend_session(), drive_client=drive_client)
    monkeypatch.setattr(ReportExporter, "from_env", Mock(return_value=exporter))

    exit_code = export_reports.main(["--type", "clients"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert (
        "Google Drive error: Google Drive API request failed while creating spreadsheet "
        f"'Mini CRM - Clients Report - 2026-07-17 12-45'. {DRIVE_AUTH_REASON}"
    ) in captured.err
    assert "Hint:" in captured.err and "Google OAuth credentials" in captured.err
    assert RAW_AUTH_DETAIL not in captured.err
    assert "invalid_grant" not in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""
    exporter.sheets_client_factory.assert_not_called()


def test_cli_sheets_auth_failure_after_creation_keeps_spreadsheet_details(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    drive_client = Mock()
    drive_client.create_google_spreadsheet.return_value = {
        "id": "sheet-42",
        "name": "Report",
        "webViewLink": "https://docs.test/sheet-42",
    }
    sheets_client, _ = sheets_client_failing_auth(SHEETS_AUTH_FAILURES[0].values[0], "sheet-42")
    exporter = _real_exporter(
        session=_healthy_backend_session(), drive_client=drive_client, sheets_client=sheets_client
    )
    monkeypatch.setattr(ReportExporter, "from_env", Mock(return_value=exporter))

    exit_code = export_reports.main(["--type", "clients"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Report export failed:" in captured.err
    assert SHEETS_AUTH_REASON.rstrip(".") in captured.err
    assert "unexpected" not in captured.err
    assert "spreadsheet_id=sheet-42" in captured.err
    assert "web_view_link=https://docs.test/sheet-42" in captured.err
    assert RAW_AUTH_DETAIL not in captured.err
    assert "Traceback" not in captured.err
    drive_client.delete_file.assert_not_called()


@pytest.mark.parametrize("content", MALFORMED_SERVICE_ACCOUNT_FILES)
def test_cli_malformed_service_account_file_after_creation_keeps_spreadsheet_details(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path, content
) -> None:
    # Real exporter and real Sheets client: the key file is only parsed once the
    # client is first used, i.e. after Drive has created the spreadsheet.
    credentials_path = write_credential_file(tmp_path, content)
    drive_client = Mock()
    drive_client.create_google_spreadsheet.return_value = {
        "id": "sheet-42",
        "name": "Report",
        "webViewLink": "https://docs.test/sheet-42",
    }
    sheets_client = GoogleSheetsClient(
        spreadsheet_id="sheet-42",
        credentials_path=credentials_path,
        service_builder=Mock(),
    )
    exporter = _real_exporter(
        session=_healthy_backend_session(), drive_client=drive_client, sheets_client=sheets_client
    )
    monkeypatch.setattr(ReportExporter, "from_env", Mock(return_value=exporter))

    exit_code = export_reports.main(["--type", "clients"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Report export failed:" in captured.err
    assert SHEETS_INVALID_CREDENTIALS_MESSAGE.rstrip(".") in captured.err
    assert "unexpected" not in captured.err
    assert "spreadsheet_id=sheet-42" in captured.err
    assert "web_view_link=https://docs.test/sheet-42" in captured.err
    assert RAW_SECRET not in captured.err
    assert str(credentials_path) not in captured.err
    assert "Traceback" not in captured.err
    drive_client.delete_file.assert_not_called()


# Files whose real parser errors are not ValueErrors, so they are the ones at risk of
# escaping as an "unexpected" error: null/number client secrets raise TypeError, a
# non-object token raises AttributeError.
DRIVE_CREDENTIAL_FILE_CASES = [
    pytest.param("client_secret", "null", id="client-secret-json-null"),
    pytest.param("client_secret", '{"installed": 5}', id="client-secret-installed-not-object"),
    pytest.param("client_secret", "{not json", id="client-secret-invalid-json"),
    pytest.param("token", "[1]", id="token-json-list"),
    pytest.param("token", "{not json", id="token-invalid-json"),
]


def _drive_client_with_bad_file(tmp_path: Path, kind: str, content: str) -> tuple[GoogleDriveClient, Path]:
    bad_path = write_credential_file(tmp_path, content, f"{kind}.json")
    other_path = tmp_path / ("token.json" if kind == "client_secret" else "client_secret.json")
    client = GoogleDriveClient(
        client_secret_path=bad_path if kind == "client_secret" else other_path,
        token_path=bad_path if kind == "token" else other_path,
    )
    return client, bad_path


@pytest.mark.parametrize(("kind", "content"), DRIVE_CREDENTIAL_FILE_CASES)
def test_cli_malformed_drive_credential_file_prints_message_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path, kind, content
) -> None:
    drive_client, bad_path = _drive_client_with_bad_file(tmp_path, kind, content)
    exporter = _real_exporter(session=_healthy_backend_session(), drive_client=drive_client)
    monkeypatch.setattr(ReportExporter, "from_env", Mock(return_value=exporter))

    exit_code = export_reports.main(["--type", "clients"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert f"Google Drive error: {DRIVE_AUTHENTICATION_MESSAGE}" in captured.err
    assert "Hint:" in captured.err and "Google OAuth credentials" in captured.err
    assert "unexpected" not in captured.err
    assert RAW_SECRET not in captured.err
    assert str(bad_path) not in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""
    exporter.sheets_client_factory.assert_not_called()


def test_cli_does_not_swallow_programming_errors_raised_inside_drive_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drive_client, _ = drive_client_failing_with(TypeError("programming error"))
    exporter = _real_exporter(session=_healthy_backend_session(), drive_client=drive_client)
    monkeypatch.setattr(ReportExporter, "from_env", Mock(return_value=exporter))

    with pytest.raises(TypeError, match="programming error"):
        export_reports.main(["--type", "clients"])


def test_cli_process_with_missing_config_prints_message_and_exits_one() -> None:
    # Real process, real config loading: no network or Google credentials involved.
    # Empty variables win over any developer .env (python-dotenv never overrides).
    env = {**os.environ, "GOOGLE_OAUTH_CLIENT_SECRET_PATH": "", "GOOGLE_SERVICE_ACCOUNT_PATH": ""}

    completed = subprocess.run(
        [sys.executable, "-m", "scripts.export_reports", "--type", "clients"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 1
    assert "Configuration error:" in completed.stderr
    assert "GOOGLE_OAUTH_CLIENT_SECRET_PATH" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert completed.stdout == ""
