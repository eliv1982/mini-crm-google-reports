from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from backend.database import connection_context, contains_pattern, utc_now_iso

from .errors import DatabaseOperationError, EntityNotFoundError, InvalidReferenceError

DEFAULT_LIMIT = 50
MAX_LIMIT = 100

TASK_COLUMNS = (
    "id",
    "title",
    "description",
    "client_id",
    "deal_id",
    "due_date",
    "completed",
    "created_at",
    "updated_at",
)

UPDATE_FIELDS = ("title", "description", "client_id", "deal_id", "due_date")


def _row_to_task(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["completed"] = bool(payload["completed"])
    return payload


def _fetch_task(connection: sqlite3.Connection, task_id: int) -> dict[str, Any]:
    row = connection.execute(
        f"SELECT {', '.join(TASK_COLUMNS)} FROM tasks WHERE id = ?",
        (task_id,),
    ).fetchone()
    if row is None:
        raise EntityNotFoundError("Task", task_id)
    return _row_to_task(row)


def _ensure_client_exists(connection: sqlite3.Connection, client_id: int | None) -> None:
    if client_id is None:
        return
    row = connection.execute("SELECT 1 FROM clients WHERE id = ?", (client_id,)).fetchone()
    if row is None:
        raise InvalidReferenceError("client_id", client_id)


def _ensure_deal_exists(connection: sqlite3.Connection, deal_id: int | None) -> None:
    if deal_id is None:
        return
    row = connection.execute("SELECT 1 FROM deals WHERE id = ?", (deal_id,)).fetchone()
    if row is None:
        raise InvalidReferenceError("deal_id", deal_id)


def create_task(
    data: Mapping[str, Any],
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    timestamp = utc_now_iso()
    try:
        with connection_context(database_path) as connection:
            _ensure_client_exists(connection, data.get("client_id"))
            _ensure_deal_exists(connection, data.get("deal_id"))
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    title,
                    description,
                    client_id,
                    deal_id,
                    due_date,
                    completed,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["title"],
                    data.get("description"),
                    data.get("client_id"),
                    data.get("deal_id"),
                    data.get("due_date"),
                    int(bool(data.get("completed", False))),
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            return _fetch_task(connection, cursor.lastrowid)
    except InvalidReferenceError:
        raise
    except sqlite3.DatabaseError as exc:
        raise DatabaseOperationError("Failed to create task.") from exc


def get_task_by_id(
    task_id: int,
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    try:
        with connection_context(database_path) as connection:
            return _fetch_task(connection, task_id)
    except sqlite3.DatabaseError as exc:
        raise DatabaseOperationError("Failed to fetch task.") from exc


def list_tasks(
    *,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    database_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    return search_tasks(limit=limit, offset=offset, database_path=database_path)


def search_tasks(
    *,
    search: str | None = None,
    client_id: int | None = None,
    deal_id: int | None = None,
    completed: bool | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    database_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    query = f"SELECT {', '.join(TASK_COLUMNS)} FROM tasks"
    conditions: list[str] = []
    params: list[Any] = []

    normalized_search = (search or "").strip()
    if normalized_search:
        pattern = contains_pattern(normalized_search)
        conditions.append(
            "("
            "title LIKE ? COLLATE NOCASE ESCAPE '\\' OR "
            "COALESCE(description, '') LIKE ? COLLATE NOCASE ESCAPE '\\'"
            ")"
        )
        params.extend([pattern, pattern])

    if client_id is not None:
        conditions.append("client_id = ?")
        params.append(client_id)

    if deal_id is not None:
        conditions.append("deal_id = ?")
        params.append(deal_id)

    if completed is not None:
        conditions.append("completed = ?")
        params.append(int(completed))

    if conditions:
        query = f"{query} WHERE {' AND '.join(conditions)}"

    query = f"{query} ORDER BY id ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    try:
        with connection_context(database_path) as connection:
            rows = connection.execute(query, params).fetchall()
            return [_row_to_task(row) for row in rows]
    except sqlite3.DatabaseError as exc:
        raise DatabaseOperationError("Failed to list tasks.") from exc


def update_task(
    task_id: int,
    data: Mapping[str, Any],
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    update_payload = {field: data[field] for field in UPDATE_FIELDS if field in data}
    try:
        with connection_context(database_path) as connection:
            existing_task = _fetch_task(connection, task_id)
            if "client_id" in update_payload:
                _ensure_client_exists(connection, update_payload["client_id"])
            if "deal_id" in update_payload:
                _ensure_deal_exists(connection, update_payload["deal_id"])
            if not update_payload:
                return existing_task

            assignments: list[str] = []
            params: list[Any] = []
            for field in UPDATE_FIELDS:
                if field in update_payload:
                    assignments.append(f"{field} = ?")
                    params.append(update_payload[field])

            assignments.append("updated_at = ?")
            params.append(utc_now_iso())
            params.append(task_id)

            connection.execute(
                f"UPDATE tasks SET {', '.join(assignments)} WHERE id = ?",
                params,
            )
            connection.commit()
            return _fetch_task(connection, task_id)
    except (EntityNotFoundError, InvalidReferenceError):
        raise
    except sqlite3.DatabaseError as exc:
        raise DatabaseOperationError("Failed to update task.") from exc


def set_task_completed(
    task_id: int,
    completed: bool,
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    try:
        with connection_context(database_path) as connection:
            _fetch_task(connection, task_id)
            connection.execute(
                "UPDATE tasks SET completed = ?, updated_at = ? WHERE id = ?",
                (int(completed), utc_now_iso(), task_id),
            )
            connection.commit()
            return _fetch_task(connection, task_id)
    except EntityNotFoundError:
        raise
    except sqlite3.DatabaseError as exc:
        raise DatabaseOperationError("Failed to update task completion.") from exc


def delete_task(
    task_id: int,
    database_path: str | Path | None = None,
) -> None:
    try:
        with connection_context(database_path) as connection:
            _fetch_task(connection, task_id)
            connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            connection.commit()
    except EntityNotFoundError:
        raise
    except sqlite3.DatabaseError as exc:
        raise DatabaseOperationError("Failed to delete task.") from exc
