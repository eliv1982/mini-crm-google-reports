from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import Any, Callable, Sequence

PASTE_SEQUENCES = ("<Control-v>", "<Control-V>", "<Shift-Insert>")
CONTEXT_MENU_SEQUENCE = "<Button-3>"


def is_editable_text_widget(widget: Any) -> bool:
    widget_class = widget.winfo_class()
    if widget_class not in {"Entry", "TEntry", "Text"}:
        return False
    try:
        state = str(widget.cget("state"))
    except Exception:
        state = "normal"
    return state not in {"readonly", "disabled"}


def enable_clipboard_shortcuts(
    widget: Any,
    *,
    menu_factory: Callable[[Any], Any] | None = None,
) -> Any | None:
    if not is_editable_text_widget(widget):
        return None
    if getattr(widget, "_mini_crm_clipboard_enabled", False):
        return getattr(widget, "_mini_crm_context_menu", None)

    context_menu = _build_context_menu(widget, menu_factory=menu_factory)

    for sequence in PASTE_SEQUENCES:
        widget.bind(sequence, _handle_paste_event, add="+")
    widget.bind(CONTEXT_MENU_SEQUENCE, lambda event: _show_context_menu(event, context_menu), add="+")

    widget._mini_crm_clipboard_enabled = True
    widget._mini_crm_context_menu = context_menu
    return context_menu


def paste_clipboard_into_widget(widget: Any) -> str:
    try:
        clipboard_text = widget.clipboard_get()
    except Exception:
        return "break"

    if not clipboard_text:
        return "break"

    _insert_text_into_widget(widget, clipboard_text)
    return "break"


def _handle_paste_event(event: tk.Event) -> str:
    return paste_clipboard_into_widget(event.widget)


def _build_context_menu(widget: Any, *, menu_factory: Callable[[Any], Any] | None = None) -> Any:
    menu = (menu_factory or (lambda target_widget: tk.Menu(target_widget, tearoff=False)))(widget)
    menu.add_command(label="Cut", command=lambda: _cut_selection(widget))
    menu.add_command(label="Copy", command=lambda: _copy_selection(widget))
    menu.add_command(label="Paste", command=lambda: paste_clipboard_into_widget(widget))
    menu.add_command(label="Select All", command=lambda: _select_all(widget))
    return menu


def _show_context_menu(event: tk.Event, context_menu: Any) -> str:
    try:
        event.widget.focus_set()
        context_menu.tk_popup(event.x_root, event.y_root)
    finally:
        try:
            context_menu.grab_release()
        except Exception:
            pass
    return "break"


def _insert_text_into_widget(widget: Any, text: str) -> None:
    widget_class = widget.winfo_class()
    if widget_class in {"Entry", "TEntry"}:
        if _entry_has_selection(widget):
            widget.delete("sel.first", "sel.last")
        widget.insert("insert", text)
        return

    if widget_class == "Text":
        if _text_has_selection(widget):
            widget.delete("sel.first", "sel.last")
        widget.insert("insert", text)
        try:
            widget.see("insert")
        except Exception:
            pass


def _copy_selection(widget: Any) -> None:
    try:
        selection = widget.selection_get()
    except Exception:
        return
    try:
        widget.clipboard_clear()
        widget.clipboard_append(selection)
    except Exception:
        return


def _cut_selection(widget: Any) -> None:
    if widget.winfo_class() == "Text":
        if not _text_has_selection(widget):
            return
    elif not _entry_has_selection(widget):
        return

    _copy_selection(widget)
    try:
        widget.delete("sel.first", "sel.last")
    except Exception:
        return


def _select_all(widget: Any) -> str:
    widget_class = widget.winfo_class()
    if widget_class in {"Entry", "TEntry"}:
        widget.selection_range(0, "end")
        widget.icursor("end")
        return "break"
    if widget_class == "Text":
        widget.tag_add("sel", "1.0", "end-1c")
        widget.mark_set("insert", "end-1c")
        try:
            widget.see("insert")
        except Exception:
            pass
        return "break"
    return "break"


def _entry_has_selection(widget: Any) -> bool:
    try:
        return bool(widget.selection_present())
    except Exception:
        return False


def _text_has_selection(widget: Any) -> bool:
    try:
        return bool(widget.tag_ranges("sel"))
    except Exception:
        return False


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: str = "entry"
    required: bool = False
    options: Sequence[str] | None = None
    width: int = 36


class RecordDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        title: str,
        fields: Sequence[FieldSpec],
        initial_values: dict[str, Any] | None = None,
        on_submit: Callable[[dict[str, str]], None],
    ) -> None:
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._fields = list(fields)
        self._on_submit = on_submit
        self._widgets: dict[str, ttk.Entry | ttk.Combobox] = {}
        self._values = {key: self._normalize_value(value) for key, value in (initial_values or {}).items()}

        container = ttk.Frame(self, padding=16)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(1, weight=1)

        for row_index, field in enumerate(self._fields):
            ttk.Label(container, text=field.label).grid(
                row=row_index,
                column=0,
                sticky="w",
                padx=(0, 8),
                pady=4,
            )
            widget = self._build_widget(container, field)
            widget.grid(row=row_index, column=1, sticky="ew", pady=4)
            self._widgets[field.key] = widget

        button_row = len(self._fields)
        button_frame = ttk.Frame(container)
        button_frame.grid(row=button_row, column=0, columnspan=2, sticky="e", pady=(12, 0))

        ttk.Button(button_frame, text="Cancel", command=self.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(button_frame, text="Save", command=self._submit).grid(row=0, column=1)

        self.bind("<Return>", lambda _event: self._submit())
        self.bind("<Escape>", lambda _event: self.destroy())

        self.update_idletasks()
        self._center_on_parent(parent.winfo_toplevel())
        self._focus_first_widget()

    def _build_widget(self, parent: ttk.Frame, field: FieldSpec) -> ttk.Entry | ttk.Combobox:
        if field.kind == "combobox":
            widget = ttk.Combobox(parent, state="readonly", width=field.width, values=list(field.options or ()))
        else:
            widget = ttk.Entry(parent, width=field.width)

        initial_value = self._values.get(field.key, "")
        if isinstance(widget, ttk.Combobox):
            widget.set(initial_value)
        else:
            widget.insert(0, initial_value)
            enable_clipboard_shortcuts(widget)
        return widget

    def _submit(self) -> None:
        payload: dict[str, str] = {}
        for field in self._fields:
            widget = self._widgets[field.key]
            payload[field.key] = self._normalize_value(widget.get())
        try:
            self._on_submit(payload)
        except Exception as error:
            messagebox.showerror(self.title() or "Mini CRM", str(error), parent=self)

    @staticmethod
    def _normalize_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "True" if value else "False"
        return str(value)

    def _focus_first_widget(self) -> None:
        if self._fields:
            self._widgets[self._fields[0].key].focus_set()

    def _center_on_parent(self, parent: tk.Misc) -> None:
        parent.update_idletasks()
        x_position = parent.winfo_rootx() + max((parent.winfo_width() - self.winfo_width()) // 2, 0)
        y_position = parent.winfo_rooty() + max((parent.winfo_height() - self.winfo_height()) // 2, 0)
        self.geometry(f"+{x_position}+{y_position}")


class ReportResultDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        report_name: str,
        records_count: int,
        url: str,
        on_open: Callable[[], None],
        on_copy_url: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title("Report created")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        container = ttk.Frame(self, padding=16)
        container.grid(row=0, column=0, sticky="nsew")

        ttk.Label(container, text="Report created successfully.").grid(row=0, column=0, sticky="w")
        ttk.Label(container, text=f"Records: {records_count}").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(container, text=report_name).grid(row=2, column=0, sticky="w", pady=(4, 0))

        url_entry = ttk.Entry(container, width=60)
        url_entry.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        url_entry.insert(0, url)
        url_entry.configure(state="readonly")

        buttons = ttk.Frame(container)
        buttons.grid(row=4, column=0, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Open", command=on_open).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Copy URL", command=on_copy_url).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(buttons, text="Close", command=self.destroy).grid(row=0, column=2)

        self.bind("<Escape>", lambda _event: self.destroy())
        self.update_idletasks()
        self._center_on_parent(parent.winfo_toplevel())

    def _center_on_parent(self, parent: tk.Misc) -> None:
        parent.update_idletasks()
        x_position = parent.winfo_rootx() + max((parent.winfo_width() - self.winfo_width()) // 2, 0)
        y_position = parent.winfo_rooty() + max((parent.winfo_height() - self.winfo_height()) // 2, 0)
        self.geometry(f"+{x_position}+{y_position}")
