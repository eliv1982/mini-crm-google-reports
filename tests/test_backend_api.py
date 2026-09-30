from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_clients_crud_endpoints(client: TestClient) -> None:
    create_response = client.post(
        "/clients",
        json={
            "name": "Alice Adams",
            "company": "Acme Corp",
            "email": "alice@acme.example",
        },
    )
    assert create_response.status_code == 201
    created_client = create_response.json()
    client_id = created_client["id"]

    get_response = client.get(f"/clients/{client_id}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Alice Adams"

    list_response = client.get(
        "/clients",
        params={"search": "alice", "status": "active", "limit": 10, "offset": 0},
    )
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [client_id]

    update_response = client.patch(
        f"/clients/{client_id}",
        json={"company": "Acme North"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["company"] == "Acme North"

    archive_response = client.post(f"/clients/{client_id}/archive")
    assert archive_response.status_code == 200
    assert archive_response.json()["status"] == "archived"

    delete_response = client.delete(f"/clients/{client_id}")
    assert delete_response.status_code == 204

    missing_response = client.get(f"/clients/{client_id}")
    assert missing_response.status_code == 404


def test_deals_crud_endpoints(client: TestClient) -> None:
    client_response = client.post("/clients", json={"name": "Boris"})
    client_id = client_response.json()["id"]

    create_response = client.post(
        "/deals",
        json={
            "title": "Expansion deal",
            "client_id": client_id,
            "amount": 1500.0,
            "status": "in_progress",
        },
    )
    assert create_response.status_code == 201
    deal = create_response.json()
    deal_id = deal["id"]

    get_response = client.get(f"/deals/{deal_id}")
    assert get_response.status_code == 200
    assert get_response.json()["client_id"] == client_id

    list_response = client.get(
        "/deals",
        params={"search": "expansion", "client_id": client_id, "status": "in_progress"},
    )
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [deal_id]

    update_response = client.patch(
        f"/deals/{deal_id}",
        json={"status": "won", "amount": 2200.0},
    )
    assert update_response.status_code == 200
    assert update_response.json()["status"] == "won"
    assert update_response.json()["amount"] == 2200.0

    delete_response = client.delete(f"/deals/{deal_id}")
    assert delete_response.status_code == 204

    missing_response = client.get(f"/deals/{deal_id}")
    assert missing_response.status_code == 404


def test_tasks_crud_endpoints(client: TestClient) -> None:
    client_response = client.post("/clients", json={"name": "Carla"})
    client_id = client_response.json()["id"]
    deal_response = client.post(
        "/deals",
        json={"title": "New contract", "client_id": client_id, "amount": 500.0},
    )
    deal_id = deal_response.json()["id"]

    create_response = client.post(
        "/tasks",
        json={
            "title": "Prepare kickoff",
            "description": "Send agenda",
            "client_id": client_id,
            "deal_id": deal_id,
        },
    )
    assert create_response.status_code == 201
    task = create_response.json()
    task_id = task["id"]

    get_response = client.get(f"/tasks/{task_id}")
    assert get_response.status_code == 200
    assert get_response.json()["deal_id"] == deal_id

    list_response = client.get(
        "/tasks",
        params={"search": "agenda", "client_id": client_id, "deal_id": deal_id},
    )
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [task_id]

    update_response = client.patch(
        f"/tasks/{task_id}",
        json={"description": "Send agenda and notes"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["description"] == "Send agenda and notes"

    complete_response = client.post(f"/tasks/{task_id}/complete")
    assert complete_response.status_code == 200
    assert complete_response.json()["completed"] is True

    reopen_response = client.post(f"/tasks/{task_id}/reopen")
    assert reopen_response.status_code == 200
    assert reopen_response.json()["completed"] is False

    completed_filter_response = client.get("/tasks", params={"completed": "false"})
    assert completed_filter_response.status_code == 200
    assert [item["id"] for item in completed_filter_response.json()] == [task_id]

    delete_response = client.delete(f"/tasks/{task_id}")
    assert delete_response.status_code == 204

    missing_response = client.get(f"/tasks/{task_id}")
    assert missing_response.status_code == 404


def test_api_returns_validation_and_reference_errors(client: TestClient) -> None:
    invalid_client_response = client.post(
        "/clients",
        json={"name": " ", "email": "not-an-email"},
    )
    assert invalid_client_response.status_code == 422

    invalid_deal_response = client.post(
        "/deals",
        json={"title": "Broken deal", "client_id": 999, "amount": 10.0},
    )
    assert invalid_deal_response.status_code == 400
    assert "client_id" in invalid_deal_response.json()["detail"]

    invalid_amount_response = client.post(
        "/deals",
        json={"title": "Negative", "amount": -1},
    )
    assert invalid_amount_response.status_code == 422

    invalid_task_response = client.post(
        "/tasks",
        json={"title": "Broken task", "deal_id": 999},
    )
    assert invalid_task_response.status_code == 400
    assert "deal_id" in invalid_task_response.json()["detail"]

    invalid_status_response = client.get("/clients", params={"status": "paused"})
    assert invalid_status_response.status_code == 422


def test_api_returns_404_for_missing_entities(client: TestClient) -> None:
    assert client.get("/clients/999").status_code == 404
    assert client.get("/deals/999").status_code == 404
    assert client.get("/tasks/999").status_code == 404
    assert client.post("/tasks/999/complete").status_code == 404


@pytest.mark.parametrize(
    ("resource", "field"),
    [("clients", "name"), ("deals", "title"), ("tasks", "title")],
)
@pytest.mark.parametrize(
    ("term", "expected"),
    [("%", ["100% Reliable"]), ("_", ["snake_case"])],
)
def test_search_treats_percent_and_underscore_literally(
    client: TestClient,
    resource: str,
    field: str,
    term: str,
    expected: list[str],
) -> None:
    for value in ["100% Reliable", "1000 Reliable", "snake_case", "snakeXcase"]:
        assert client.post(f"/{resource}", json={field: value}).status_code == 201

    response = client.get(f"/{resource}", params={"search": term})

    assert response.status_code == 200
    assert [item[field] for item in response.json()] == expected
