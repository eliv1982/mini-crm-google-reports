from __future__ import annotations

from pathlib import Path

import pytest

from backend.repositories import clients as clients_repository
from backend.repositories import deals as deals_repository
from backend.repositories import tasks as tasks_repository
from backend.repositories.errors import EntityNotFoundError, InvalidReferenceError


def test_create_task_without_relations(initialized_database_path: Path) -> None:
    created = tasks_repository.create_task({"title": "Inbox cleanup"}, initialized_database_path)

    assert created["client_id"] is None
    assert created["deal_id"] is None
    assert created["completed"] is False


def test_create_task_with_client(initialized_database_path: Path) -> None:
    client = clients_repository.create_client({"name": "Dana"}, initialized_database_path)

    created = tasks_repository.create_task(
        {"title": "Call customer", "client_id": client["id"]},
        initialized_database_path,
    )

    assert created["client_id"] == client["id"]


def test_create_task_with_deal(initialized_database_path: Path) -> None:
    deal = deals_repository.create_deal(
        {"title": "Support retainer", "amount": 900.0},
        initialized_database_path,
    )

    created = tasks_repository.create_task(
        {"title": "Prepare proposal", "deal_id": deal["id"]},
        initialized_database_path,
    )

    assert created["deal_id"] == deal["id"]


def test_create_task_rejects_invalid_references(initialized_database_path: Path) -> None:
    with pytest.raises(InvalidReferenceError, match="client_id"):
        tasks_repository.create_task(
            {"title": "Invalid client task", "client_id": 999},
            initialized_database_path,
        )

    with pytest.raises(InvalidReferenceError, match="deal_id"):
        tasks_repository.create_task(
            {"title": "Invalid deal task", "deal_id": 999},
            initialized_database_path,
        )


def test_complete_and_reopen_task(initialized_database_path: Path) -> None:
    task = tasks_repository.create_task({"title": "Send contract"}, initialized_database_path)

    completed = tasks_repository.set_task_completed(task["id"], True, initialized_database_path)
    reopened = tasks_repository.set_task_completed(task["id"], False, initialized_database_path)

    assert completed["completed"] is True
    assert reopened["completed"] is False


def test_task_filters_and_delete(initialized_database_path: Path) -> None:
    client = clients_repository.create_client({"name": "Erik"}, initialized_database_path)
    deal = deals_repository.create_deal(
        {"title": "Upsell", "client_id": client["id"], "amount": 800.0},
        initialized_database_path,
    )
    first = tasks_repository.create_task(
        {
            "title": "Draft summary",
            "description": "Follow up with client",
            "client_id": client["id"],
            "deal_id": deal["id"],
        },
        initialized_database_path,
    )
    second = tasks_repository.create_task(
        {"title": "Internal prep", "description": "Ops review"},
        initialized_database_path,
    )
    tasks_repository.set_task_completed(first["id"], True, initialized_database_path)

    assert [item["id"] for item in tasks_repository.search_tasks(search="follow", database_path=initialized_database_path)] == [first["id"]]
    assert [item["id"] for item in tasks_repository.search_tasks(client_id=client["id"], database_path=initialized_database_path)] == [first["id"]]
    assert [item["id"] for item in tasks_repository.search_tasks(deal_id=deal["id"], database_path=initialized_database_path)] == [first["id"]]
    assert [item["id"] for item in tasks_repository.search_tasks(completed=True, database_path=initialized_database_path)] == [first["id"]]

    tasks_repository.delete_task(second["id"], initialized_database_path)

    with pytest.raises(EntityNotFoundError):
        tasks_repository.get_task_by_id(second["id"], initialized_database_path)
