from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.database import connection_context, contains_pattern, initialize_database


def test_initialize_database_creates_tables(initialized_database_path: Path) -> None:
    with sqlite3.connect(initialized_database_path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()

    table_names = {row[0] for row in rows}
    assert {"clients", "deals", "tasks"}.issubset(table_names)


def test_connection_context_enables_foreign_keys(
    initialized_database_path: Path,
) -> None:
    with connection_context(initialized_database_path) as connection:
        foreign_keys_enabled = connection.execute("PRAGMA foreign_keys;").fetchone()[0]

    assert foreign_keys_enabled == 1


def test_initialize_database_creates_parent_directory(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "crm.db"

    initialize_database(database_path)

    assert database_path.exists()


def test_contains_pattern_escapes_like_wildcards_and_escape_character() -> None:
    assert contains_pattern("plain") == "%plain%"
    assert contains_pattern("50%_off") == "%50\\%\\_off%"
    assert contains_pattern("a\\b") == "%a\\\\b%"
    assert contains_pattern("\\%") == "%\\\\\\%%"
