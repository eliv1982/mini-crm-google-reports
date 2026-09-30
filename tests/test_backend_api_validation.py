from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.repositories import deals as deals_repository
from backend.repositories import tasks as tasks_repository

NON_NULLABLE_UPDATE_FIELDS = [
    ("clients", "name"),
    ("clients", "status"),
    ("deals", "title"),
    ("deals", "amount"),
    ("deals", "status"),
    ("tasks", "title"),
]

NULLABLE_UPDATE_FIELDS = [
    ("clients", "company"),
    ("clients", "email"),
    ("clients", "phone"),
    ("deals", "client_id"),
    ("deals", "expected_close_date"),
    ("tasks", "description"),
    ("tasks", "client_id"),
    ("tasks", "deal_id"),
    ("tasks", "due_date"),
]

# One nullable field per resource, used to update a record without touching the rest.
SINGLE_FIELD_UPDATES = {
    "clients": {"company": "Renamed Co"},
    "deals": {"expected_close_date": "2026-10-01"},
    "tasks": {"description": "Changed"},
}

INVALID_DATES = [
    "not-a-date",
    "2026-02-30",
    "2027-02-29",
    "2026-13-01",
    "2026-8-1",
    "20260801",
    "2026-08-01T10:00:00",
    "2026-W31-6",
    "01/08/2026",
]

# (resource, date field, minimal valid create payload)
DATE_ENDPOINTS = [
    ("deals", "expected_close_date", {"title": "Dated deal"}),
    ("tasks", "due_date", {"title": "Dated task"}),
]


def _create_populated_records(client: TestClient) -> dict[str, dict[str, Any]]:
    """Create one fully populated client, deal and task, keyed by resource."""
    client_record = client.post(
        "/clients",
        json={
            "name": "Full Client",
            "company": "Acme",
            "email": "full@acme.example",
            "phone": "+10000000000",
        },
    ).json()
    deal_record = client.post(
        "/deals",
        json={
            "title": "Full deal",
            "client_id": client_record["id"],
            "amount": 100.0,
            "status": "in_progress",
            "expected_close_date": "2026-09-01",
        },
    ).json()
    task_record = client.post(
        "/tasks",
        json={
            "title": "Full task",
            "description": "Details",
            "client_id": client_record["id"],
            "deal_id": deal_record["id"],
            "due_date": "2026-09-02",
        },
    ).json()
    return {"clients": client_record, "deals": deal_record, "tasks": task_record}


@pytest.mark.parametrize(("resource", "field"), NON_NULLABLE_UPDATE_FIELDS)
def test_patch_rejects_explicit_null_for_non_nullable_fields(
    client: TestClient,
    resource: str,
    field: str,
) -> None:
    record = _create_populated_records(client)[resource]

    response = client.patch(f"/{resource}/{record['id']}", json={field: None})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", field]
    assert client.get(f"/{resource}/{record['id']}").json() == record


@pytest.mark.parametrize("resource", ["clients", "deals", "tasks"])
def test_patch_allows_omitting_non_nullable_fields(
    client: TestClient,
    resource: str,
) -> None:
    record = _create_populated_records(client)[resource]

    empty_response = client.patch(f"/{resource}/{record['id']}", json={})
    assert empty_response.status_code == 200
    assert empty_response.json() == record

    changes = SINGLE_FIELD_UPDATES[resource]
    partial_response = client.patch(f"/{resource}/{record['id']}", json=changes)
    assert partial_response.status_code == 200
    updated = partial_response.json()
    for field, value in changes.items():
        assert updated[field] == value
    unchanged = {key: value for key, value in record.items() if key not in {*changes, "updated_at"}}
    assert {key: updated[key] for key in unchanged} == unchanged


@pytest.mark.parametrize(("resource", "field"), NULLABLE_UPDATE_FIELDS)
def test_patch_clears_nullable_fields_with_explicit_null(
    client: TestClient,
    resource: str,
    field: str,
) -> None:
    record = _create_populated_records(client)[resource]
    assert record[field] is not None

    response = client.patch(f"/{resource}/{record['id']}", json={field: None})

    assert response.status_code == 200
    assert response.json()[field] is None
    assert client.get(f"/{resource}/{record['id']}").json()[field] is None


@pytest.mark.parametrize("value", INVALID_DATES)
@pytest.mark.parametrize(("resource", "field", "base_payload"), DATE_ENDPOINTS)
def test_create_rejects_invalid_dates(
    client: TestClient,
    resource: str,
    field: str,
    base_payload: dict[str, Any],
    value: str,
) -> None:
    response = client.post(f"/{resource}", json={**base_payload, field: value})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", field]
    assert client.get(f"/{resource}").json() == []


@pytest.mark.parametrize("value", INVALID_DATES)
@pytest.mark.parametrize(("resource", "field", "base_payload"), DATE_ENDPOINTS)
def test_update_rejects_invalid_dates(
    client: TestClient,
    resource: str,
    field: str,
    base_payload: dict[str, Any],
    value: str,
) -> None:
    record = _create_populated_records(client)[resource]

    response = client.patch(f"/{resource}/{record['id']}", json={field: value})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", field]
    assert client.get(f"/{resource}/{record['id']}").json() == record


@pytest.mark.parametrize("value", ["2026-08-01", "2028-02-29", "0001-01-01"])
@pytest.mark.parametrize(("resource", "field", "base_payload"), DATE_ENDPOINTS)
def test_valid_iso_dates_are_stored_unchanged(
    client: TestClient,
    resource: str,
    field: str,
    base_payload: dict[str, Any],
    value: str,
) -> None:
    created = client.post(f"/{resource}", json={**base_payload, field: value})
    assert created.status_code == 201
    assert created.json()[field] == value

    record = _create_populated_records(client)[resource]
    updated = client.patch(f"/{resource}/{record['id']}", json={field: value})
    assert updated.status_code == 200
    assert updated.json()[field] == value


@pytest.mark.parametrize(("resource", "field", "base_payload"), DATE_ENDPOINTS)
def test_null_omitted_and_blank_dates_remain_valid(
    client: TestClient,
    resource: str,
    field: str,
    base_payload: dict[str, Any],
) -> None:
    omitted = client.post(f"/{resource}", json=base_payload)
    assert omitted.status_code == 201
    assert omitted.json()[field] is None

    explicit_null = client.post(f"/{resource}", json={**base_payload, field: None})
    assert explicit_null.status_code == 201
    assert explicit_null.json()[field] is None

    blank = client.post(f"/{resource}", json={**base_payload, field: "   "})
    assert blank.status_code == 201
    assert blank.json()[field] is None

    record = _create_populated_records(client)[resource]
    assert record[field] is not None

    untouched = client.patch(f"/{resource}/{record['id']}", json={"title": "Retitled"})
    assert untouched.status_code == 200
    assert untouched.json()[field] == record[field]

    cleared = client.patch(f"/{resource}/{record['id']}", json={field: None})
    assert cleared.status_code == 200
    assert cleared.json()[field] is None


def test_existing_malformed_dates_stay_readable(
    client: TestClient,
    initialized_database_path: Path,
) -> None:
    # Rows written before validation existed must not break read endpoints.
    deal = deals_repository.create_deal(
        {"title": "Legacy deal", "expected_close_date": "legacy-value"},
        initialized_database_path,
    )
    task = tasks_repository.create_task(
        {"title": "Legacy task", "due_date": "legacy-value"},
        initialized_database_path,
    )

    deal_response = client.get(f"/deals/{deal['id']}")
    task_response = client.get(f"/tasks/{task['id']}")

    assert deal_response.status_code == 200
    assert deal_response.json()["expected_close_date"] == "legacy-value"
    assert task_response.status_code == 200
    assert task_response.json()["due_date"] == "legacy-value"
    assert client.get("/deals").status_code == 200
    assert client.get("/tasks").status_code == 200
