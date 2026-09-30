from __future__ import annotations

from pathlib import Path

import pytest

from backend.repositories import clients as clients_repository
from backend.repositories.errors import EntityNotFoundError


def test_client_crud_lifecycle(initialized_database_path: Path) -> None:
    created = clients_repository.create_client(
        {
            "name": "Alice Johnson",
            "company": "Acme",
            "email": "alice@example.com",
            "phone": "+10000000000",
            "status": "active",
        },
        initialized_database_path,
    )

    fetched = clients_repository.get_client_by_id(created["id"], initialized_database_path)
    assert fetched == created

    updated = clients_repository.update_client(
        created["id"],
        {"company": "Acme North", "phone": "+12223334444"},
        initialized_database_path,
    )
    assert updated["company"] == "Acme North"
    assert updated["phone"] == "+12223334444"

    archived = clients_repository.archive_client(created["id"], initialized_database_path)
    assert archived["status"] == "archived"

    clients_repository.delete_client(created["id"], initialized_database_path)

    with pytest.raises(EntityNotFoundError):
        clients_repository.get_client_by_id(created["id"], initialized_database_path)


def test_list_clients_returns_ordered_results(initialized_database_path: Path) -> None:
    first = clients_repository.create_client({"name": "Alice"}, initialized_database_path)
    second = clients_repository.create_client({"name": "Bob"}, initialized_database_path)
    third = clients_repository.create_client({"name": "Carla"}, initialized_database_path)

    listed = clients_repository.list_clients(database_path=initialized_database_path)

    assert [item["id"] for item in listed] == [first["id"], second["id"], third["id"]]


def test_search_clients_matches_name_company_and_email(
    initialized_database_path: Path,
) -> None:
    clients_repository.create_client(
        {
            "name": "Daria",
            "company": "Northwind Labs",
            "email": "daria@northwind.example",
        },
        initialized_database_path,
    )
    clients_repository.create_client({"name": "Elena", "company": "Other Co"}, initialized_database_path)

    assert len(clients_repository.search_clients(search="northwind", database_path=initialized_database_path)) == 1
    assert len(clients_repository.search_clients(search="daria@", database_path=initialized_database_path)) == 1


def test_search_clients_filters_by_status(initialized_database_path: Path) -> None:
    active_client = clients_repository.create_client({"name": "Fedor"}, initialized_database_path)
    archived_client = clients_repository.create_client({"name": "Gina"}, initialized_database_path)
    clients_repository.archive_client(archived_client["id"], initialized_database_path)

    active_results = clients_repository.search_clients(
        status="active",
        database_path=initialized_database_path,
    )
    archived_results = clients_repository.search_clients(
        status="archived",
        database_path=initialized_database_path,
    )

    assert [item["id"] for item in active_results] == [active_client["id"]]
    assert [item["id"] for item in archived_results] == [archived_client["id"]]


def test_list_clients_supports_pagination(initialized_database_path: Path) -> None:
    clients_repository.create_client({"name": "Helen"}, initialized_database_path)
    second = clients_repository.create_client({"name": "Ilya"}, initialized_database_path)
    third = clients_repository.create_client({"name": "Julia"}, initialized_database_path)

    paginated = clients_repository.list_clients(
        limit=2,
        offset=1,
        database_path=initialized_database_path,
    )

    assert [item["id"] for item in paginated] == [second["id"], third["id"]]


def test_search_clients_treats_wildcards_literally(initialized_database_path: Path) -> None:
    def create(**fields: str) -> int:
        return clients_repository.create_client(fields, initialized_database_path)["id"]

    percent = create(name="100% Club")
    create(name="1000 Club")
    underscore = create(name="Snake_Case")
    create(name="SnakeXCase")
    backslash = create(name="Back\\slash")
    company_underscore = create(name="Co One", company="Acme_Labs")
    create(name="Co Two", company="AcmeXLabs")
    email_underscore = create(name="Mail One", email="user_1@example.com")
    create(name="Mail Two", email="userA1@example.com")

    def search(term: str) -> list[int]:
        results = clients_repository.search_clients(
            search=term,
            database_path=initialized_database_path,
        )
        return [item["id"] for item in results]

    assert search("%") == [percent]
    assert search("100%") == [percent]
    assert search("_") == [underscore, company_underscore, email_underscore]
    assert search("snake_case") == [underscore]
    assert search("\\") == [backslash]
    assert search("acme_labs") == [company_underscore]
    assert search("user_1@") == [email_underscore]
