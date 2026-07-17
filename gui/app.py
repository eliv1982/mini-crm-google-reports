from __future__ import annotations

import sys
import threading
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import Any, Callable, Sequence

from reports import ReportExportError, ReportExportResult, ReportExporter

from .api_client import GUIAPIError, MiniCRMGUIAPIClient
from .dialogs import FieldSpec, RecordDialog, ReportResultDialog, enable_clipboard_shortcuts

WINDOW_TITLE = "Mini CRM"
WINDOW_SIZE = "1180x720"
DEFAULT_FETCH_LIMIT = 100


class GUIValidationError(ValueError):
    """Raised when GUI form input is invalid."""


@dataclass(frozen=True)
class TabAction:
    text: str
    command_name: str


def parse_reference_id(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    identifier, *_rest = normalized.split(" - ", 1)
    try:
        return int(identifier)
    except ValueError as exc:
        raise GUIValidationError(f"Invalid selection value: {value!r}") from exc


def format_reference_value(identifier: int | None, label: str | None) -> str:
    if identifier is None:
        return ""
    return f"{identifier} - {label or 'Unknown'}"


def dispatch_report_export(
    report_type: str,
    exporter_factory: Callable[[], ReportExporter] = ReportExporter.from_env,
) -> ReportExportResult:
    exporter = exporter_factory()
    export_method = {
        "clients": exporter.export_clients_report,
        "deals": exporter.export_deals_report,
        "tasks": exporter.export_tasks_report,
    }.get(report_type)
    if export_method is None:
        raise GUIValidationError(f"Unsupported report type: {report_type}")
    return export_method()


class EntityTab:
    def __init__(
        self,
        app: "MiniCRMApp",
        notebook: ttk.Notebook,
        *,
        title: str,
        columns: Sequence[tuple[str, str, int]],
    ) -> None:
        self.app = app
        self.frame = ttk.Frame(notebook, padding=12)
        notebook.add(self.frame, text=title)
        self.columns = list(columns)

        self.search_var = tk.StringVar()
        self.export_button: ttk.Button | None = None

        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)

        self._build_search_row()
        self.tree = self._build_tree()
        self._bind_double_click()

    def _build_search_row(self) -> None:
        controls = ttk.Frame(self.frame)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="Search").grid(row=0, column=0, sticky="w", padx=(0, 8))
        search_entry = ttk.Entry(controls, textvariable=self.search_var)
        search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        search_entry.bind("<Return>", lambda _event: self.refresh_records())
        enable_clipboard_shortcuts(search_entry)

        ttk.Button(controls, text="Search", command=self.refresh_records).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(controls, text="Clear search", command=self.clear_search).grid(row=0, column=3)

    def _build_tree(self) -> ttk.Treeview:
        tree_frame = ttk.Frame(self.frame)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        tree = ttk.Treeview(
            tree_frame,
            columns=[column_id for column_id, _label, _width in self.columns],
            show="headings",
            selectmode="browse",
        )
        tree.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)

        for column_id, label, width in self.columns:
            tree.heading(column_id, text=label)
            tree.column(column_id, width=width, anchor="w")

        return tree

    def _bind_double_click(self) -> None:
        self.tree.bind("<Double-1>", self._on_double_click)

    def _on_double_click(self, _event: tk.Event) -> None:
        if self.tree.selection():
            self.on_edit()

    def selected_record_id(self) -> int | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def clear_search(self) -> None:
        self.search_var.set("")
        self.refresh_records()

    def set_rows(self, rows: Sequence[dict[str, Any]], value_builder: Callable[[dict[str, Any]], Sequence[Any]]) -> None:
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            self.tree.insert("", "end", iid=str(row["id"]), values=list(value_builder(row)))

    def refresh_records(self) -> None:
        raise NotImplementedError

    def on_edit(self) -> None:
        raise NotImplementedError


class ClientsTab(EntityTab):
    def __init__(self, app: "MiniCRMApp", notebook: ttk.Notebook) -> None:
        super().__init__(
            app,
            notebook,
            title="Clients",
            columns=[
                ("id", "ID", 70),
                ("name", "Name", 180),
                ("company", "Company", 180),
                ("email", "Email", 220),
                ("phone", "Phone", 150),
                ("status", "Status", 100),
            ],
        )
        self._build_buttons()

    def _build_buttons(self) -> None:
        buttons = ttk.Frame(self.frame)
        buttons.grid(row=2, column=0, sticky="w", pady=(8, 0))

        for column_index, action in enumerate(
            [
                TabAction("Refresh", "refresh_records"),
                TabAction("Add", "add_client"),
                TabAction("Edit", "on_edit"),
                TabAction("Archive", "archive_client"),
                TabAction("Delete", "delete_client"),
                TabAction("Export report", "export_report"),
            ]
        ):
            button = ttk.Button(buttons, text=action.text, command=getattr(self, action.command_name))
            button.grid(row=0, column=column_index, padx=(0, 8))
            if action.command_name == "export_report":
                self.export_button = button

    def refresh_records(self) -> None:
        try:
            records = self.app.api_client.list_clients(search=self.search_var.get().strip() or None)
        except GUIAPIError as error:
            self.app.show_error("Could not load clients.", error)
            return
        self.set_rows(
            records,
            lambda client: [
                client.get("id"),
                client.get("name"),
                client.get("company") or "",
                client.get("email") or "",
                client.get("phone") or "",
                client.get("status"),
            ],
        )

    def add_client(self) -> None:
        self._open_dialog(title="Add client", initial_values=None, on_save=self._create_client)

    def on_edit(self) -> None:
        client_id = self.selected_record_id()
        if client_id is None:
            messagebox.showinfo(WINDOW_TITLE, "Select a client first.")
            return
        try:
            client = self.app.api_client.get_client(client_id)
        except GUIAPIError as error:
            self.app.show_error("Could not load client details.", error)
            return
        self._open_dialog(title="Edit client", initial_values=client, on_save=lambda payload: self._update_client(client_id, payload))

    def archive_client(self) -> None:
        client_id = self.selected_record_id()
        if client_id is None:
            messagebox.showinfo(WINDOW_TITLE, "Select a client first.")
            return
        if not messagebox.askyesno(WINDOW_TITLE, "Archive the selected client?"):
            return
        try:
            self.app.api_client.archive_client(client_id)
        except GUIAPIError as error:
            self.app.show_error("Could not archive the client.", error)
            return
        self.refresh_records()

    def delete_client(self) -> None:
        client_id = self.selected_record_id()
        if client_id is None:
            messagebox.showinfo(WINDOW_TITLE, "Select a client first.")
            return
        if not messagebox.askyesno(WINDOW_TITLE, "Delete the selected client?"):
            return
        try:
            self.app.api_client.delete_client(client_id)
        except GUIAPIError as error:
            self.app.show_error("Could not delete the client.", error)
            return
        self.refresh_records()

    def export_report(self) -> None:
        self.app.start_report_export("clients", self.export_button)

    def _open_dialog(
        self,
        *,
        title: str,
        initial_values: dict[str, Any] | None,
        on_save: Callable[[dict[str, str]], None],
    ) -> None:
        RecordDialog(
            self.frame,
            title=title,
            fields=[
                FieldSpec("name", "Name", required=True),
                FieldSpec("company", "Company"),
                FieldSpec("email", "Email"),
                FieldSpec("phone", "Phone"),
                FieldSpec("status", "Status", kind="combobox", options=("active", "archived"), required=True),
            ],
            initial_values=initial_values or {"status": "active"},
            on_submit=lambda payload: self._submit_client_form(payload, on_save),
        )

    def _submit_client_form(self, values: dict[str, str], on_save: Callable[[dict[str, str]], None]) -> None:
        payload = {
            "name": self.app.require_text(values.get("name"), "Name"),
            "status": self.app.require_text(values.get("status"), "Status"),
        }
        optional_fields = ("company", "email", "phone")
        payload.update(self.app.optional_payload(values, optional_fields))
        on_save(payload)

    def _create_client(self, payload: dict[str, str]) -> None:
        try:
            self.app.api_client.create_client(payload)
        except GUIAPIError as error:
            self.app.show_error("Could not create the client.", error)
            return
        self.app.close_active_dialog()
        self.refresh_records()

    def _update_client(self, client_id: int, payload: dict[str, str]) -> None:
        try:
            self.app.api_client.update_client(client_id, payload)
        except GUIAPIError as error:
            self.app.show_error("Could not update the client.", error)
            return
        self.app.close_active_dialog()
        self.refresh_records()


class DealsTab(EntityTab):
    def __init__(self, app: "MiniCRMApp", notebook: ttk.Notebook) -> None:
        super().__init__(
            app,
            notebook,
            title="Deals",
            columns=[
                ("id", "ID", 70),
                ("title", "Title", 260),
                ("client_id", "Client ID", 100),
                ("amount", "Amount", 110),
                ("status", "Status", 120),
                ("expected_close_date", "Expected Close Date", 150),
            ],
        )
        self._build_buttons()

    def _build_buttons(self) -> None:
        buttons = ttk.Frame(self.frame)
        buttons.grid(row=2, column=0, sticky="w", pady=(8, 0))

        for column_index, action in enumerate(
            [
                TabAction("Refresh", "refresh_records"),
                TabAction("Add", "add_deal"),
                TabAction("Edit", "on_edit"),
                TabAction("Delete", "delete_deal"),
                TabAction("Export report", "export_report"),
            ]
        ):
            button = ttk.Button(buttons, text=action.text, command=getattr(self, action.command_name))
            button.grid(row=0, column=column_index, padx=(0, 8))
            if action.command_name == "export_report":
                self.export_button = button

    def refresh_records(self) -> None:
        try:
            records = self.app.api_client.list_deals(search=self.search_var.get().strip() or None)
        except GUIAPIError as error:
            self.app.show_error("Could not load deals.", error)
            return
        self.set_rows(
            records,
            lambda deal: [
                deal.get("id"),
                deal.get("title"),
                deal.get("client_id") or "",
                deal.get("amount"),
                deal.get("status"),
                deal.get("expected_close_date") or "",
            ],
        )

    def add_deal(self) -> None:
        self._open_dialog(title="Add deal", initial_values=None, on_save=self._create_deal)

    def on_edit(self) -> None:
        deal_id = self.selected_record_id()
        if deal_id is None:
            messagebox.showinfo(WINDOW_TITLE, "Select a deal first.")
            return
        try:
            deal = self.app.api_client.get_deal(deal_id)
        except GUIAPIError as error:
            self.app.show_error("Could not load deal details.", error)
            return
        self._open_dialog(title="Edit deal", initial_values=deal, on_save=lambda payload: self._update_deal(deal_id, payload))

    def delete_deal(self) -> None:
        deal_id = self.selected_record_id()
        if deal_id is None:
            messagebox.showinfo(WINDOW_TITLE, "Select a deal first.")
            return
        if not messagebox.askyesno(WINDOW_TITLE, "Delete the selected deal?"):
            return
        try:
            self.app.api_client.delete_deal(deal_id)
        except GUIAPIError as error:
            self.app.show_error("Could not delete the deal.", error)
            return
        self.refresh_records()

    def export_report(self) -> None:
        self.app.start_report_export("deals", self.export_button)

    def _open_dialog(
        self,
        *,
        title: str,
        initial_values: dict[str, Any] | None,
        on_save: Callable[[dict[str, Any]], None],
    ) -> None:
        try:
            client_options = [""] + [format_reference_value(client["id"], client["name"]) for client in self.app.fetch_clients_for_selection(initial_values)]
        except GUIAPIError as error:
            self.app.show_error("Could not load clients for the deal form.", error)
            return

        initial_payload = dict(initial_values or {})
        initial_payload["client_id"] = format_reference_value(initial_values.get("client_id"), self.app.lookup_client_name(initial_values.get("client_id"))) if initial_values else ""

        RecordDialog(
            self.frame,
            title=title,
            fields=[
                FieldSpec("title", "Title", required=True),
                FieldSpec("client_id", "Client", kind="combobox", options=client_options),
                FieldSpec("amount", "Amount", required=True),
                FieldSpec("status", "Status", kind="combobox", options=("new", "in_progress", "won", "lost"), required=True),
                FieldSpec("expected_close_date", "Expected Close Date"),
            ],
            initial_values=initial_payload or {"status": "new"},
            on_submit=lambda payload: self._submit_deal_form(payload, on_save),
        )

    def _submit_deal_form(self, values: dict[str, str], on_save: Callable[[dict[str, Any]], None]) -> None:
        payload: dict[str, Any] = {
            "title": self.app.require_text(values.get("title"), "Title"),
            "status": self.app.require_text(values.get("status"), "Status"),
            "amount": self.app.parse_float(values.get("amount"), "Amount"),
        }
        client_id = parse_reference_id(values.get("client_id"))
        if client_id is not None:
            payload["client_id"] = client_id
        payload.update(self.app.optional_payload(values, ("expected_close_date",)))
        on_save(payload)

    def _create_deal(self, payload: dict[str, Any]) -> None:
        try:
            self.app.api_client.create_deal(payload)
        except GUIAPIError as error:
            self.app.show_error("Could not create the deal.", error)
            return
        self.app.close_active_dialog()
        self.refresh_records()
        self.app.clients_cache = None

    def _update_deal(self, deal_id: int, payload: dict[str, Any]) -> None:
        try:
            self.app.api_client.update_deal(deal_id, payload)
        except GUIAPIError as error:
            self.app.show_error("Could not update the deal.", error)
            return
        self.app.close_active_dialog()
        self.refresh_records()
        self.app.clients_cache = None


class TasksTab(EntityTab):
    def __init__(self, app: "MiniCRMApp", notebook: ttk.Notebook) -> None:
        super().__init__(
            app,
            notebook,
            title="Tasks",
            columns=[
                ("id", "ID", 70),
                ("title", "Title", 220),
                ("client_id", "Client ID", 100),
                ("deal_id", "Deal ID", 100),
                ("due_date", "Due Date", 130),
                ("completed", "Completed", 110),
            ],
        )
        self._build_buttons()

    def _build_buttons(self) -> None:
        buttons = ttk.Frame(self.frame)
        buttons.grid(row=2, column=0, sticky="w", pady=(8, 0))

        for column_index, action in enumerate(
            [
                TabAction("Refresh", "refresh_records"),
                TabAction("Add", "add_task"),
                TabAction("Edit", "on_edit"),
                TabAction("Complete / Reopen", "toggle_completion"),
                TabAction("Delete", "delete_task"),
                TabAction("Export report", "export_report"),
            ]
        ):
            button = ttk.Button(buttons, text=action.text, command=getattr(self, action.command_name))
            button.grid(row=0, column=column_index, padx=(0, 8))
            if action.command_name == "export_report":
                self.export_button = button

    def refresh_records(self) -> None:
        try:
            records = self.app.api_client.list_tasks(search=self.search_var.get().strip() or None)
        except GUIAPIError as error:
            self.app.show_error("Could not load tasks.", error)
            return
        self.set_rows(
            records,
            lambda task: [
                task.get("id"),
                task.get("title"),
                task.get("client_id") or "",
                task.get("deal_id") or "",
                task.get("due_date") or "",
                "Yes" if task.get("completed") else "No",
            ],
        )

    def add_task(self) -> None:
        self._open_dialog(title="Add task", initial_values=None, on_save=self._create_task)

    def on_edit(self) -> None:
        task_id = self.selected_record_id()
        if task_id is None:
            messagebox.showinfo(WINDOW_TITLE, "Select a task first.")
            return
        try:
            task = self.app.api_client.get_task(task_id)
        except GUIAPIError as error:
            self.app.show_error("Could not load task details.", error)
            return
        self._open_dialog(title="Edit task", initial_values=task, on_save=lambda payload: self._update_task(task_id, payload))

    def toggle_completion(self) -> None:
        task_id = self.selected_record_id()
        if task_id is None:
            messagebox.showinfo(WINDOW_TITLE, "Select a task first.")
            return
        try:
            task = self.app.api_client.get_task(task_id)
            if task.get("completed"):
                self.app.api_client.reopen_task(task_id)
            else:
                self.app.api_client.complete_task(task_id)
        except GUIAPIError as error:
            self.app.show_error("Could not update task completion.", error)
            return
        self.refresh_records()

    def delete_task(self) -> None:
        task_id = self.selected_record_id()
        if task_id is None:
            messagebox.showinfo(WINDOW_TITLE, "Select a task first.")
            return
        if not messagebox.askyesno(WINDOW_TITLE, "Delete the selected task?"):
            return
        try:
            self.app.api_client.delete_task(task_id)
        except GUIAPIError as error:
            self.app.show_error("Could not delete the task.", error)
            return
        self.refresh_records()

    def export_report(self) -> None:
        self.app.start_report_export("tasks", self.export_button)

    def _open_dialog(
        self,
        *,
        title: str,
        initial_values: dict[str, Any] | None,
        on_save: Callable[[dict[str, Any]], None],
    ) -> None:
        try:
            client_options = [""] + [format_reference_value(client["id"], client["name"]) for client in self.app.fetch_clients_for_selection(initial_values)]
            deal_options = [""] + [format_reference_value(deal["id"], deal["title"]) for deal in self.app.fetch_deals_for_selection(initial_values)]
        except GUIAPIError as error:
            self.app.show_error("Could not load linked records for the task form.", error)
            return

        initial_payload = dict(initial_values or {})
        if initial_values:
            initial_payload["client_id"] = format_reference_value(initial_values.get("client_id"), self.app.lookup_client_name(initial_values.get("client_id")))
            initial_payload["deal_id"] = format_reference_value(initial_values.get("deal_id"), self.app.lookup_deal_title(initial_values.get("deal_id")))

        RecordDialog(
            self.frame,
            title=title,
            fields=[
                FieldSpec("title", "Title", required=True),
                FieldSpec("description", "Description"),
                FieldSpec("client_id", "Client", kind="combobox", options=client_options),
                FieldSpec("deal_id", "Deal", kind="combobox", options=deal_options),
                FieldSpec("due_date", "Due Date"),
            ],
            initial_values=initial_payload,
            on_submit=lambda payload: self._submit_task_form(payload, on_save),
        )

    def _submit_task_form(self, values: dict[str, str], on_save: Callable[[dict[str, Any]], None]) -> None:
        payload: dict[str, Any] = {"title": self.app.require_text(values.get("title"), "Title")}
        payload.update(self.app.optional_payload(values, ("description", "due_date")))
        client_id = parse_reference_id(values.get("client_id"))
        deal_id = parse_reference_id(values.get("deal_id"))
        if client_id is not None:
            payload["client_id"] = client_id
        if deal_id is not None:
            payload["deal_id"] = deal_id
        on_save(payload)

    def _create_task(self, payload: dict[str, Any]) -> None:
        try:
            self.app.api_client.create_task(payload)
        except GUIAPIError as error:
            self.app.show_error("Could not create the task.", error)
            return
        self.app.close_active_dialog()
        self.refresh_records()
        self.app.deals_cache = None
        self.app.clients_cache = None

    def _update_task(self, task_id: int, payload: dict[str, Any]) -> None:
        try:
            self.app.api_client.update_task(task_id, payload)
        except GUIAPIError as error:
            self.app.show_error("Could not update the task.", error)
            return
        self.app.close_active_dialog()
        self.refresh_records()
        self.app.deals_cache = None
        self.app.clients_cache = None


class MiniCRMApp:
    def __init__(self, root: tk.Tk, api_client: MiniCRMGUIAPIClient | None = None) -> None:
        self.root = root
        self.api_client = api_client or MiniCRMGUIAPIClient()
        self.root.title(WINDOW_TITLE)
        self.root.geometry(WINDOW_SIZE)
        self.root.minsize(980, 640)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.clients_cache: list[dict[str, Any]] | None = None
        self.deals_cache: list[dict[str, Any]] | None = None

        self.status_var = tk.StringVar(value="Backend: Checking...")
        self._dialogs: list[tk.Toplevel] = []

        container = ttk.Frame(root, padding=12)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(container)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        self.clients_tab = ClientsTab(self, self.notebook)
        self.deals_tab = DealsTab(self, self.notebook)
        self.tasks_tab = TasksTab(self, self.notebook)

        status_bar = ttk.Label(container, textvariable=self.status_var, anchor="w")
        status_bar.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        if self.check_backend_status():
            self.refresh_all_tabs()

    def refresh_all_tabs(self) -> None:
        self.clients_tab.refresh_records()
        self.deals_tab.refresh_records()
        self.tasks_tab.refresh_records()

    def check_backend_status(self) -> bool:
        try:
            online = self.api_client.check_health()
        except GUIAPIError as error:
            self.status_var.set("Backend: Offline")
            print(f"Backend check failed: {error}", file=sys.stderr)
            return False
        self.status_var.set("Backend: Online" if online else "Backend: Offline")
        return online

    def fetch_clients_for_selection(self, current_record: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if self.clients_cache is None:
            self.clients_cache = self.api_client.get_all_clients()
        return self._ensure_reference_present(
            self.clients_cache,
            current_record.get("client_id") if current_record else None,
            lambda record_id: self.api_client.get_client(record_id),
        )

    def fetch_deals_for_selection(self, current_record: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if self.deals_cache is None:
            self.deals_cache = self.api_client.get_all_deals()
        return self._ensure_reference_present(
            self.deals_cache,
            current_record.get("deal_id") if current_record else None,
            lambda record_id: self.api_client.get_deal(record_id),
        )

    def lookup_client_name(self, client_id: int | None) -> str | None:
        if client_id is None:
            return None
        for client in self.clients_cache or []:
            if client.get("id") == client_id:
                return str(client.get("name"))
        return None

    def lookup_deal_title(self, deal_id: int | None) -> str | None:
        if deal_id is None:
            return None
        for deal in self.deals_cache or []:
            if deal.get("id") == deal_id:
                return str(deal.get("title"))
        return None

    def _ensure_reference_present(
        self,
        records: list[dict[str, Any]],
        record_id: int | None,
        loader: Callable[[int], dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if record_id is None:
            return list(records)
        if any(record.get("id") == record_id for record in records):
            return list(records)
        missing_record = loader(record_id)
        return list(records) + [missing_record]

    def show_error(self, user_message: str, error: Exception) -> None:
        print(f"{user_message} {error}", file=sys.stderr)
        messagebox.showerror(WINDOW_TITLE, f"{user_message}\n\n{error}")

    def require_text(self, value: str | None, label: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise GUIValidationError(f"{label} is required.")
        return normalized

    def parse_float(self, value: str | None, label: str) -> float:
        normalized = self.require_text(value, label)
        try:
            return float(normalized)
        except ValueError as exc:
            raise GUIValidationError(f"{label} must be a valid number.") from exc

    def optional_payload(self, values: dict[str, str], keys: Sequence[str]) -> dict[str, str]:
        payload: dict[str, str] = {}
        for key in keys:
            normalized = values.get(key, "").strip()
            if normalized:
                payload[key] = normalized
        return payload

    def close_active_dialog(self) -> None:
        current_focus = self.root.focus_get()
        top_level = current_focus.winfo_toplevel() if current_focus is not None else None
        if isinstance(top_level, tk.Toplevel) and top_level is not self.root:
            top_level.destroy()

    def start_report_export(self, report_type: str, button: ttk.Button | None) -> None:
        if button is not None:
            button.configure(state="disabled")

        def worker() -> None:
            try:
                result = dispatch_report_export(report_type)
            except Exception as error:
                self.root.after(0, lambda: self._finish_report_export(button, error=error))
                return
            self.root.after(0, lambda: self._finish_report_export(button, result=result))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_report_export(
        self,
        button: ttk.Button | None,
        *,
        result: ReportExportResult | None = None,
        error: Exception | None = None,
    ) -> None:
        if button is not None:
            button.configure(state="normal")

        if error is not None:
            if isinstance(error, (ReportExportError, GUIValidationError)):
                messagebox.showerror(WINDOW_TITLE, str(error))
            else:
                print(f"Unexpected report export error: {error}", file=sys.stderr)
                messagebox.showerror(WINDOW_TITLE, "Report export failed.")
            return

        if result is None:
            return

        ReportResultDialog(
            self.root,
            report_name=result.name,
            records_count=result.records_count,
            url=result.web_view_link,
            on_open=lambda: webbrowser.open(result.web_view_link),
            on_copy_url=lambda: self.copy_to_clipboard(result.web_view_link),
        )

    def copy_to_clipboard(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()


def create_app() -> MiniCRMApp:
    root = tk.Tk()
    return MiniCRMApp(root)
