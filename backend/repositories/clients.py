from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from backend.database import connection_context, utc_now_iso

from .errors import DatabaseOperationError, EntityNotFoundError

DEFAULT_LIMIT = 50
MAX_LIMIT = 100

CLIENT_COLUMNS = (
    "id",
    "name",
    "company",
    "email",
    "phone",
    "status",
    "created_at",
    "updated_at",
)

UPDATE_FIELDS = ("name", "company", "email", "phone", "status")


def _row_to_client(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _fetch_client(connection: sqlite3.Connection, client_id: int) -> dict[str, Any]:
    row = connection.execute(
        f"SELECT {', '.join(CLIENT_COLUMNS)} FROM clients WHERE id = ?",
        (client_id,),
    ).fetchone()
    if row is None:
        raise EntityNotFoundError("Client", client_id)
    return _row_to_client(row)


def create_client(
    data: Mapping[str, Any],
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    timestamp = utc_now_iso()
    try:
        with connection_context(database_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO clients (name, company, email, phone, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["name"],
                    data.get("company"),
                    data.get("email"),
                    data.get("phone"),
                    data.get("status", "active"),
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            return _fetch_client(connection, cursor.lastrowid)
    except sqlite3.DatabaseError as exc:
        raise DatabaseOperationError("Failed to create client.") from exc


def get_client_by_id(
    client_id: int,
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    try:
        with connection_context(database_path) as connection:
            return _fetch_client(connection, client_id)
    except sqlite3.DatabaseError as exc:
        raise DatabaseOperationError("Failed to fetch client.") from exc


def list_clients(
    *,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    database_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    return search_clients(limit=limit, offset=offset, database_path=database_path)


def search_clients(
    *,
    search: str | None = None,
    status: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    database_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    query = f"SELECT {', '.join(CLIENT_COLUMNS)} FROM clients"
    conditions: list[str] = []
    params: list[Any] = []

    normalized_search = (search or "").strip()
    if normalized_search:
        pattern = f"%{normalized_search}%"
        conditions.append(
            "("
            "name LIKE ? COLLATE NOCASE OR "
            "COALESCE(company, '') LIKE ? COLLATE NOCASE OR "
            "COALESCE(email, '') LIKE ? COLLATE NOCASE"
            ")"
        )
        params.extend([pattern, pattern, pattern])

    if status:
        conditions.append("status = ?")
        params.append(status)

    if conditions:
        query = f"{query} WHERE {' AND '.join(conditions)}"

    query = f"{query} ORDER BY id ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    try:
        with connection_context(database_path) as connection:
            rows = connection.execute(query, params).fetchall()
            return [_row_to_client(row) for row in rows]
    except sqlite3.DatabaseError as exc:
        raise DatabaseOperationError("Failed to list clients.") from exc


def update_client(
    client_id: int,
    data: Mapping[str, Any],
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    update_payload = {field: data[field] for field in UPDATE_FIELDS if field in data}
    try:
        with connection_context(database_path) as connection:
            existing_client = _fetch_client(connection, client_id)
            if not update_payload:
                return existing_client

            assignments: list[str] = []
            params: list[Any] = []
            for field in UPDATE_FIELDS:
                if field in update_payload:
                    assignments.append(f"{field} = ?")
                    params.append(update_payload[field])

            assignments.append("updated_at = ?")
            params.append(utc_now_iso())
            params.append(client_id)

            connection.execute(
                f"UPDATE clients SET {', '.join(assignments)} WHERE id = ?",
                params,
            )
            connection.commit()
            return _fetch_client(connection, client_id)
    except EntityNotFoundError:
        raise
    except sqlite3.DatabaseError as exc:
        raise DatabaseOperationError("Failed to update client.") from exc


def archive_client(
    client_id: int,
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    return update_client(client_id, {"status": "archived"}, database_path)


def delete_client(
    client_id: int,
    database_path: str | Path | None = None,
) -> None:
    try:
        with connection_context(database_path) as connection:
            _fetch_client(connection, client_id)
            connection.execute("DELETE FROM clients WHERE id = ?", (client_id,))
            connection.commit()
    except EntityNotFoundError:
        raise
    except sqlite3.DatabaseError as exc:
        raise DatabaseOperationError("Failed to delete client.") from exc
