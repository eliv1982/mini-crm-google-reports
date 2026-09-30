from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from backend.database import connection_context, contains_pattern, utc_now_iso

from .errors import DatabaseOperationError, EntityNotFoundError, InvalidReferenceError

DEFAULT_LIMIT = 50
MAX_LIMIT = 100

DEAL_COLUMNS = (
    "id",
    "title",
    "client_id",
    "amount",
    "status",
    "expected_close_date",
    "created_at",
    "updated_at",
)

UPDATE_FIELDS = ("title", "client_id", "amount", "status", "expected_close_date")


def _row_to_deal(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _fetch_deal(connection: sqlite3.Connection, deal_id: int) -> dict[str, Any]:
    row = connection.execute(
        f"SELECT {', '.join(DEAL_COLUMNS)} FROM deals WHERE id = ?",
        (deal_id,),
    ).fetchone()
    if row is None:
        raise EntityNotFoundError("Deal", deal_id)
    return _row_to_deal(row)


def _ensure_client_exists(connection: sqlite3.Connection, client_id: int | None) -> None:
    if client_id is None:
        return
    row = connection.execute("SELECT 1 FROM clients WHERE id = ?", (client_id,)).fetchone()
    if row is None:
        raise InvalidReferenceError("client_id", client_id)


def create_deal(
    data: Mapping[str, Any],
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    timestamp = utc_now_iso()
    try:
        with connection_context(database_path) as connection:
            _ensure_client_exists(connection, data.get("client_id"))
            cursor = connection.execute(
                """
                INSERT INTO deals (
                    title,
                    client_id,
                    amount,
                    status,
                    expected_close_date,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["title"],
                    data.get("client_id"),
                    data.get("amount", 0),
                    data.get("status", "new"),
                    data.get("expected_close_date"),
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            return _fetch_deal(connection, cursor.lastrowid)
    except InvalidReferenceError:
        raise
    except sqlite3.DatabaseError as exc:
        raise DatabaseOperationError("Failed to create deal.") from exc


def get_deal_by_id(
    deal_id: int,
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    try:
        with connection_context(database_path) as connection:
            return _fetch_deal(connection, deal_id)
    except sqlite3.DatabaseError as exc:
        raise DatabaseOperationError("Failed to fetch deal.") from exc


def list_deals(
    *,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    database_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    return search_deals(limit=limit, offset=offset, database_path=database_path)


def search_deals(
    *,
    search: str | None = None,
    client_id: int | None = None,
    status: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    database_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    query = f"SELECT {', '.join(DEAL_COLUMNS)} FROM deals"
    conditions: list[str] = []
    params: list[Any] = []

    normalized_search = (search or "").strip()
    if normalized_search:
        conditions.append("title LIKE ? COLLATE NOCASE ESCAPE '\\'")
        params.append(contains_pattern(normalized_search))

    if client_id is not None:
        conditions.append("client_id = ?")
        params.append(client_id)

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
            return [_row_to_deal(row) for row in rows]
    except sqlite3.DatabaseError as exc:
        raise DatabaseOperationError("Failed to list deals.") from exc


def update_deal(
    deal_id: int,
    data: Mapping[str, Any],
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    update_payload = {field: data[field] for field in UPDATE_FIELDS if field in data}
    try:
        with connection_context(database_path) as connection:
            existing_deal = _fetch_deal(connection, deal_id)
            if "client_id" in update_payload:
                _ensure_client_exists(connection, update_payload["client_id"])
            if not update_payload:
                return existing_deal

            assignments: list[str] = []
            params: list[Any] = []
            for field in UPDATE_FIELDS:
                if field in update_payload:
                    assignments.append(f"{field} = ?")
                    params.append(update_payload[field])

            assignments.append("updated_at = ?")
            params.append(utc_now_iso())
            params.append(deal_id)

            connection.execute(
                f"UPDATE deals SET {', '.join(assignments)} WHERE id = ?",
                params,
            )
            connection.commit()
            return _fetch_deal(connection, deal_id)
    except (EntityNotFoundError, InvalidReferenceError):
        raise
    except sqlite3.DatabaseError as exc:
        raise DatabaseOperationError("Failed to update deal.") from exc


def delete_deal(
    deal_id: int,
    database_path: str | Path | None = None,
) -> None:
    try:
        with connection_context(database_path) as connection:
            _fetch_deal(connection, deal_id)
            connection.execute("DELETE FROM deals WHERE id = ?", (deal_id,))
            connection.commit()
    except EntityNotFoundError:
        raise
    except sqlite3.DatabaseError as exc:
        raise DatabaseOperationError("Failed to delete deal.") from exc
