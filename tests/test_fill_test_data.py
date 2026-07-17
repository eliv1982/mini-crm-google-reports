from __future__ import annotations

from collections import defaultdict

import pytest
import requests

from scripts import fill_test_data


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, object] | None = None,
        *,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> dict[str, object]:
        if self._payload is None:
            raise ValueError("No JSON payload")
        return self._payload


class FakeSession:
    def __init__(
        self,
        *,
        health_status: int = 200,
        fail_on: tuple[str, int] | None = None,
        fail_status_code: int = 500,
        fail_text: str = "server error",
        request_exception_on_health: Exception | None = None,
    ) -> None:
        self.health_status = health_status
        self.fail_on = fail_on
        self.fail_status_code = fail_status_code
        self.fail_text = fail_text
        self.request_exception_on_health = request_exception_on_health
        self.requests: list[dict[str, object]] = []
        self.created: dict[str, list[dict[str, object]]] = defaultdict(list)
        self.next_ids = {"clients": 1, "deals": 1, "tasks": 1}
        self.task_completion: dict[int, bool] = {}

    def request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, object] | None = None,
        timeout: int,
    ) -> FakeResponse:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "json": json,
                "timeout": timeout,
            }
        )

        if url.endswith("/health"):
            if self.request_exception_on_health is not None:
                raise self.request_exception_on_health
            if self.health_status != 200:
                return FakeResponse(self.health_status, {"detail": "unhealthy"})
            return FakeResponse(200, {"status": "ok"})

        if url.endswith("/clients"):
            return self._handle_create("clients", json or {})
        if url.endswith("/deals"):
            return self._handle_create("deals", json or {})
        if url.endswith("/tasks"):
            return self._handle_create("tasks", json or {})
        if "/tasks/" in url and url.endswith("/complete"):
            task_id = int(url.rstrip("/").split("/")[-2])
            return self._handle_task_complete(task_id)

        raise AssertionError(f"Unexpected URL in fake session: {url}")

    def _handle_create(self, entity_type: str, payload: dict[str, object]) -> FakeResponse:
        next_ordinal = len(self.created[entity_type]) + 1
        if self.fail_on == (entity_type, next_ordinal):
            return FakeResponse(self.fail_status_code, text=self.fail_text)

        record = dict(payload)
        record["id"] = self.next_ids[entity_type]
        self.next_ids[entity_type] += 1

        if entity_type == "tasks":
            record["completed"] = False
            self.task_completion[record["id"]] = False

        self.created[entity_type].append(record)
        return FakeResponse(201, record)

    def _handle_task_complete(self, task_id: int) -> FakeResponse:
        for task in self.created["tasks"]:
            if task["id"] == task_id:
                task["completed"] = True
                self.task_completion[task_id] = True
                return FakeResponse(200, dict(task))
        return FakeResponse(404, {"detail": "Task not found"})


def _build_config(
    *,
    clients: int = 3,
    deals: int = 3,
    tasks: int = 4,
    seed: int = 42,
    base_url: str = "http://api.test",
    run_identifier: str = "run-fixed",
) -> fill_test_data.FillTestDataConfig:
    return fill_test_data.FillTestDataConfig(
        clients=clients,
        deals=deals,
        tasks=tasks,
        seed=seed,
        base_url=base_url,
        run_identifier=run_identifier,
    )


def test_health_check_runs_before_generation() -> None:
    session = FakeSession(request_exception_on_health=requests.ConnectionError("boom"))

    with pytest.raises(fill_test_data.SeedDataError, match="Backend is unavailable"):
        fill_test_data.run_fill_test_data(_build_config(), session)

    assert len(session.requests) == 1
    assert session.requests[0]["url"] == "http://api.test/health"


def test_generator_creates_requested_counts() -> None:
    session = FakeSession()

    summary = fill_test_data.run_fill_test_data(
        _build_config(clients=3, deals=2, tasks=5),
        session,
    )

    assert summary.clients_created == 3
    assert summary.deals_created == 2
    assert summary.tasks_created == 5
    assert len(session.created["clients"]) == 3
    assert len(session.created["deals"]) == 2
    assert len(session.created["tasks"]) == 5


def test_deals_use_existing_client_ids() -> None:
    session = FakeSession()

    fill_test_data.run_fill_test_data(
        _build_config(clients=4, deals=6, tasks=0),
        session,
    )

    client_ids = {client["id"] for client in session.created["clients"]}
    for deal in session.created["deals"]:
        assert deal["client_id"] is None or deal["client_id"] in client_ids


def test_tasks_use_existing_ids_and_keep_consistent_relations() -> None:
    session = FakeSession()

    fill_test_data.run_fill_test_data(
        _build_config(clients=5, deals=5, tasks=8),
        session,
    )

    client_ids = {client["id"] for client in session.created["clients"]}
    deals_by_id = {deal["id"]: deal for deal in session.created["deals"]}
    tasks_with_both = []

    for task in session.created["tasks"]:
        assert task["client_id"] is None or task["client_id"] in client_ids
        assert task["deal_id"] is None or task["deal_id"] in deals_by_id
        if task["client_id"] is not None and task["deal_id"] is not None:
            tasks_with_both.append(task)
            deal_client_id = deals_by_id[task["deal_id"]]["client_id"]
            if deal_client_id is not None:
                assert task["client_id"] == deal_client_id

    assert tasks_with_both


def test_reproducibility_with_same_seed_and_run_identifier() -> None:
    first_session = FakeSession()
    second_session = FakeSession()
    config = _build_config(clients=3, deals=3, tasks=4, seed=99, run_identifier="same-run")

    first_summary = fill_test_data.run_fill_test_data(config, first_session)
    second_summary = fill_test_data.run_fill_test_data(config, second_session)

    assert first_summary == second_summary
    assert first_session.created == second_session.created


def test_different_run_identifiers_prevent_email_conflicts() -> None:
    first_session = FakeSession()
    second_session = FakeSession()

    fill_test_data.run_fill_test_data(
        _build_config(run_identifier="run-one", tasks=0, deals=0),
        first_session,
    )
    fill_test_data.run_fill_test_data(
        _build_config(run_identifier="run-two", tasks=0, deals=0),
        second_session,
    )

    first_emails = {client["email"] for client in first_session.created["clients"]}
    second_emails = {client["email"] for client in second_session.created["clients"]}

    assert first_emails.isdisjoint(second_emails)


def test_api_error_produces_clear_failure() -> None:
    session = FakeSession(fail_on=("clients", 2), fail_status_code=422, fail_text="bad payload")

    with pytest.raises(fill_test_data.SeedDataError, match="Client #2 failed with HTTP 422"):
        fill_test_data.run_fill_test_data(
            _build_config(clients=3, deals=0, tasks=0),
            session,
        )


def test_custom_counts_and_base_url_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKEND_URL", "http://env-backend.test")

    parsed_args = fill_test_data.parse_args(
        ["--clients", "2", "--deals", "1", "--tasks", "4", "--seed", "7"]
    )
    assert parsed_args.base_url == "http://env-backend.test"

    custom_session = FakeSession()
    config = fill_test_data.build_config(
        [
            "--clients",
            "2",
            "--deals",
            "1",
            "--tasks",
            "4",
            "--seed",
            "7",
            "--base-url",
            "http://custom-backend.test",
        ],
        run_identifier="cli-run",
    )

    fill_test_data.run_fill_test_data(config, custom_session)

    urls = {request["url"] for request in custom_session.requests}
    assert urls
    assert all(url.startswith("http://custom-backend.test") for url in urls)
