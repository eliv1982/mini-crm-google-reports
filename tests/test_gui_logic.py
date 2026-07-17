from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from gui.app import (
    EntityTab,
    GUIValidationError,
    MiniCRMApp,
    dispatch_report_export,
    format_reference_value,
    parse_reference_id,
)
from gui.dialogs import PASTE_SEQUENCES, enable_clipboard_shortcuts
from reports.exporter import ReportExportResult


class FakeExporter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def export_clients_report(self) -> ReportExportResult:
        self.calls.append("clients")
        return ReportExportResult("clients", "1", "Clients", "https://clients.test", 10)

    def export_deals_report(self) -> ReportExportResult:
        self.calls.append("deals")
        return ReportExportResult("deals", "2", "Deals", "https://deals.test", 20)

    def export_tasks_report(self) -> ReportExportResult:
        self.calls.append("tasks")
        return ReportExportResult("tasks", "3", "Tasks", "https://tasks.test", 30)


def test_dispatch_report_export_routes_to_expected_method() -> None:
    exporter = FakeExporter()

    result = dispatch_report_export("deals", exporter_factory=lambda: exporter)

    assert result.report_type == "deals"
    assert exporter.calls == ["deals"]


def test_parse_reference_id_handles_empty_and_formatted_values() -> None:
    assert parse_reference_id("") is None
    assert parse_reference_id("15 - Alice") == 15
    assert format_reference_value(7, "Northwind") == "7 - Northwind"


def test_parse_reference_id_raises_for_invalid_value() -> None:
    with pytest.raises(GUIValidationError, match="Invalid selection"):
        parse_reference_id("abc")


def test_dispatch_report_export_rejects_unknown_type() -> None:
    with pytest.raises(GUIValidationError, match="Unsupported report type"):
        dispatch_report_export("unknown", exporter_factory=FakeExporter)


class FakeMenu:
    def __init__(self, widget) -> None:
        self.widget = widget
        self.commands: list[str] = []
        self.popup_coordinates: tuple[int, int] | None = None
        self.released = False

    def add_command(self, *, label: str, command) -> None:
        self.commands.append(label)

    def tk_popup(self, x_root: int, y_root: int) -> None:
        self.popup_coordinates = (x_root, y_root)

    def grab_release(self) -> None:
        self.released = True


class FakeEditableWidget:
    def __init__(
        self,
        *,
        widget_class: str = "TEntry",
        state: str = "normal",
        text: str = "",
        clipboard_text: str | None = None,
    ) -> None:
        self._widget_class = widget_class
        self._state = state
        self.text = text
        self.clipboard_text = clipboard_text
        self.bindings: dict[str, tuple[object, object]] = {}
        self.selection: tuple[int, int] | None = None
        self.insert_index = len(text)
        self.clipboard_buffer = ""

    def winfo_class(self) -> str:
        return self._widget_class

    def cget(self, name: str) -> str:
        if name != "state":
            raise KeyError(name)
        return self._state

    def bind(self, sequence: str, callback, add=None) -> None:
        self.bindings[sequence] = (callback, add)

    def clipboard_get(self) -> str:
        if self.clipboard_text is None:
            raise RuntimeError("Clipboard unavailable")
        return self.clipboard_text

    def clipboard_clear(self) -> None:
        self.clipboard_buffer = ""

    def clipboard_append(self, text: str) -> None:
        self.clipboard_buffer += text

    def selection_present(self) -> bool:
        return self.selection is not None

    def delete(self, start, end=None) -> None:
        if start == "sel.first" and end == "sel.last" and self.selection is not None:
            selection_start, selection_end = self.selection
            self.text = self.text[:selection_start] + self.text[selection_end:]
            self.insert_index = selection_start
            self.selection = None
            return
        raise AssertionError(f"Unsupported delete arguments: {start!r}, {end!r}")

    def insert(self, index, text: str) -> None:
        if index != "insert":
            raise AssertionError(f"Unsupported insert index: {index!r}")
        self.text = self.text[: self.insert_index] + text + self.text[self.insert_index :]
        self.insert_index += len(text)

    def selection_get(self) -> str:
        if self.selection is None:
            raise RuntimeError("No selection")
        start, end = self.selection
        return self.text[start:end]

    def selection_range(self, start, end) -> None:
        if start != 0 or end != "end":
            raise AssertionError(f"Unsupported selection range: {start!r}, {end!r}")
        self.selection = (0, len(self.text))

    def icursor(self, index) -> None:
        if index == "end":
            self.insert_index = len(self.text)
            return
        raise AssertionError(f"Unsupported cursor index: {index!r}")

    def focus_set(self) -> None:
        return None


def test_client_reference_choices_can_include_id_beyond_first_100() -> None:
    clients = [{"id": index, "name": f"Client {index}"} for index in range(1, 206)]
    api_client = SimpleNamespace(
        get_all_clients=lambda: clients,
        get_client=lambda client_id: {"id": client_id, "name": f"Client {client_id}"},
    )
    app_stub = SimpleNamespace(
        api_client=api_client,
        clients_cache=None,
        _ensure_reference_present=lambda records, record_id, loader: MiniCRMApp._ensure_reference_present(
            SimpleNamespace(),
            records,
            record_id,
            loader,
        ),
    )

    records = MiniCRMApp.fetch_clients_for_selection(app_stub)

    assert len(records) == 205
    assert records[-1]["id"] == 205


def test_deal_reference_choices_can_include_id_beyond_first_100() -> None:
    deals = [{"id": index, "title": f"Deal {index}"} for index in range(1, 204)]
    api_client = SimpleNamespace(
        get_all_deals=lambda: deals,
        get_deal=lambda deal_id: {"id": deal_id, "title": f"Deal {deal_id}"},
    )
    app_stub = SimpleNamespace(
        api_client=api_client,
        deals_cache=None,
        _ensure_reference_present=lambda records, record_id, loader: MiniCRMApp._ensure_reference_present(
            SimpleNamespace(),
            records,
            record_id,
            loader,
        ),
    )

    records = MiniCRMApp.fetch_deals_for_selection(app_stub)

    assert len(records) == 203
    assert records[-1]["id"] == 203


def test_clipboard_helper_exists_and_binds_editable_entry() -> None:
    widget = FakeEditableWidget(text="hello world", clipboard_text="CRM")
    widget.selection = (6, 11)
    menu = enable_clipboard_shortcuts(widget, menu_factory=FakeMenu)

    assert menu is not None
    assert all(sequence in widget.bindings for sequence in PASTE_SEQUENCES)
    assert "<Button-3>" in widget.bindings
    assert menu.commands == ["Cut", "Copy", "Paste", "Select All"]

    paste_handler = widget.bindings["<Control-v>"][0]
    result = paste_handler(SimpleNamespace(widget=widget))

    assert result == "break"
    assert widget.text == "hello CRM"


def test_readonly_combobox_does_not_receive_clipboard_bindings() -> None:
    widget = FakeEditableWidget(widget_class="TCombobox", state="readonly")

    menu = enable_clipboard_shortcuts(widget, menu_factory=FakeMenu)

    assert menu is None
    assert widget.bindings == {}


def test_search_fields_and_dialog_entries_use_clipboard_helper_structurally() -> None:
    search_source = inspect.getsource(EntityTab)
    dialog_source = inspect.getsource(enable_clipboard_shortcuts.__globals__["RecordDialog"])

    assert "enable_clipboard_shortcuts(search_entry)" in search_source
    assert "enable_clipboard_shortcuts(widget)" in dialog_source
