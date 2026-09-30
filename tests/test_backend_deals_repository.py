from __future__ import annotations

from pathlib import Path

import pytest

from backend.repositories import clients as clients_repository
from backend.repositories import deals as deals_repository
from backend.repositories.errors import EntityNotFoundError, InvalidReferenceError


def test_create_deal_without_client(initialized_database_path: Path) -> None:
    created = deals_repository.create_deal(
        {"title": "Website rebuild", "amount": 1200.0, "status": "new"},
        initialized_database_path,
    )

    assert created["client_id"] is None
    assert created["amount"] == 1200.0


def test_create_deal_with_client(initialized_database_path: Path) -> None:
    client = clients_repository.create_client({"name": "Ariana"}, initialized_database_path)

    created = deals_repository.create_deal(
        {
            "title": "Annual contract",
            "client_id": client["id"],
            "amount": 4500.0,
            "status": "in_progress",
        },
        initialized_database_path,
    )

    assert created["client_id"] == client["id"]
    assert created["status"] == "in_progress"


def test_create_deal_rejects_invalid_client(initialized_database_path: Path) -> None:
    with pytest.raises(InvalidReferenceError, match="client_id"):
        deals_repository.create_deal(
            {"title": "Invalid deal", "client_id": 999, "amount": 10.0},
            initialized_database_path,
        )


def test_update_search_and_filters_for_deals(initialized_database_path: Path) -> None:
    client_a = clients_repository.create_client({"name": "Berta"}, initialized_database_path)
    client_b = clients_repository.create_client({"name": "Carlos"}, initialized_database_path)

    first = deals_repository.create_deal(
        {
            "title": "Renewal package",
            "client_id": client_a["id"],
            "amount": 1000.0,
            "status": "new",
        },
        initialized_database_path,
    )
    second = deals_repository.create_deal(
        {
            "title": "Migration project",
            "client_id": client_b["id"],
            "amount": 2500.0,
            "status": "lost",
        },
        initialized_database_path,
    )

    updated = deals_repository.update_deal(
        first["id"],
        {"status": "won", "amount": 3200.0},
        initialized_database_path,
    )

    assert updated["status"] == "won"
    assert updated["amount"] == 3200.0
    assert [item["id"] for item in deals_repository.search_deals(search="renew", database_path=initialized_database_path)] == [first["id"]]
    assert [item["id"] for item in deals_repository.search_deals(status="won", database_path=initialized_database_path)] == [first["id"]]
    assert [item["id"] for item in deals_repository.search_deals(client_id=client_b["id"], database_path=initialized_database_path)] == [second["id"]]


def test_delete_deal_removes_record(initialized_database_path: Path) -> None:
    created = deals_repository.create_deal(
        {"title": "Temporary deal", "amount": 50.0},
        initialized_database_path,
    )

    deals_repository.delete_deal(created["id"], initialized_database_path)

    with pytest.raises(EntityNotFoundError):
        deals_repository.get_deal_by_id(created["id"], initialized_database_path)


def test_search_deals_treats_wildcards_literally(initialized_database_path: Path) -> None:
    def create(title: str) -> int:
        return deals_repository.create_deal({"title": title}, initialized_database_path)["id"]

    percent = create("100% Renewal")
    create("1000 Renewal")
    underscore = create("Upsell_Q3")
    create("UpsellXQ3")
    backslash = create("Path\\Deal")

    def search(term: str) -> list[int]:
        results = deals_repository.search_deals(
            search=term,
            database_path=initialized_database_path,
        )
        return [item["id"] for item in results]

    assert search("%") == [percent]
    assert search("100%") == [percent]
    assert search("_") == [underscore]
    assert search("upsell_q") == [underscore]
    assert search("\\") == [backslash]
