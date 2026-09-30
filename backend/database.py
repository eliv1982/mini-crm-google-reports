from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "crm.db"

load_dotenv(PROJECT_ROOT / ".env", override=False)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    company TEXT,
    email TEXT,
    phone TEXT,
    status TEXT NOT NULL CHECK (status IN ('active', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    client_id INTEGER,
    amount REAL NOT NULL DEFAULT 0 CHECK (amount >= 0),
    status TEXT NOT NULL CHECK (status IN ('new', 'in_progress', 'won', 'lost')),
    expected_close_date TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    client_id INTEGER,
    deal_id INTEGER,
    due_date TEXT,
    completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE SET NULL,
    FOREIGN KEY (deal_id) REFERENCES deals(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_clients_status ON clients(status);
CREATE INDEX IF NOT EXISTS idx_deals_client_id ON deals(client_id);
CREATE INDEX IF NOT EXISTS idx_deals_status ON deals(status);
CREATE INDEX IF NOT EXISTS idx_tasks_client_id ON tasks(client_id);
CREATE INDEX IF NOT EXISTS idx_tasks_deal_id ON tasks(deal_id);
CREATE INDEX IF NOT EXISTS idx_tasks_completed ON tasks(completed);
"""


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def contains_pattern(text: str) -> str:
    """Build a LIKE pattern matching ``text`` literally as a substring.

    Backslash is the escape character, so queries using this pattern must
    add ``ESCAPE '\\'`` to the LIKE clause.
    """
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def resolve_database_path(database_path: str | Path | None = None) -> Path:
    raw_path = database_path or os.getenv("DATABASE_PATH") or DEFAULT_DATABASE_PATH
    resolved_path = Path(raw_path).expanduser()
    if not resolved_path.is_absolute():
        resolved_path = PROJECT_ROOT / resolved_path
    return resolved_path.resolve(strict=False)


def ensure_database_directory(database_path: str | Path | None = None) -> Path:
    resolved_path = resolve_database_path(database_path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    return resolved_path


def get_connection(database_path: str | Path | None = None) -> sqlite3.Connection:
    resolved_path = ensure_database_directory(database_path)
    connection = sqlite3.connect(resolved_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def close_connection(connection: sqlite3.Connection | None) -> None:
    if connection is not None:
        connection.close()


@contextmanager
def connection_context(
    database_path: str | Path | None = None,
) -> Iterator[sqlite3.Connection]:
    connection: sqlite3.Connection | None = None
    try:
        connection = get_connection(database_path)
        yield connection
    finally:
        close_connection(connection)


def create_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)
    connection.commit()


def initialize_database(database_path: str | Path | None = None) -> Path:
    resolved_path = ensure_database_directory(database_path)
    with connection_context(resolved_path) as connection:
        create_tables(connection)
    return resolved_path
