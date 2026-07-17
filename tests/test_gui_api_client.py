from __future__ import annotations

import pytest
import requests

from gui.api_client import GUIAPIError, MiniCRMGUIAPIClient


class FakeResponse:
    def __init__(self, status_code: int, payload, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse] | None = None, *, exception: Exception | None = None) -> None:
        self.responses = responses or []
        self.exception = exception
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if self.exception is not None:
            raise self.exception
        if not self.responses:
            raise AssertionError("No fake response available.")
        return self.responses.pop(0)


def test_client_list_uses_search_query() -> None:
    session = FakeSession([FakeResponse(200, [{"id": 1}])])
    client = MiniCRMGUIAPIClient(base_url="http://api.test", session=session)

    records = client.list_clients(search="alice")

    assert records == [{"id": 1}]
    assert session.calls[0]["url"] == "http://api.test/clients"
    assert session.calls[0]["params"] == {"limit": 100, "offset": 0, "search": "alice"}


def test_get_all_clients_uses_pagination_and_merges_all_pages() -> None:
    first_page = [{"id": index} for index in range(1, 101)]
    second_page = [{"id": index} for index in range(101, 201)]
    third_page = [{"id": index} for index in range(201, 206)]
    session = FakeSession(
        [
            FakeResponse(200, first_page),
            FakeResponse(200, second_page),
            FakeResponse(200, third_page),
        ]
    )
    client = MiniCRMGUIAPIClient(base_url="http://api.test", session=session)

    records = client.get_all_clients()

    assert len(records) == 205
    assert records[0]["id"] == 1
    assert records[-1]["id"] == 205
    assert [call["params"]["offset"] for call in session.calls] == [0, 100, 200]
    assert all(call["params"]["limit"] == 100 for call in session.calls)


def test_client_create_update_archive_delete_routes() -> None:
    session = FakeSession(
        [
            FakeResponse(201, {"id": 1, "name": "Alice"}),
            FakeResponse(200, {"id": 1, "name": "Alice Updated"}),
            FakeResponse(200, {"id": 1, "status": "archived"}),
            FakeResponse(204, {}),
        ]
    )
    client = MiniCRMGUIAPIClient(base_url="http://api.test", session=session)

    created = client.create_client({"name": "Alice"})
    updated = client.update_client(1, {"name": "Alice Updated"})
    archived = client.archive_client(1)
    client.delete_client(1)

    assert created["id"] == 1
    assert updated["name"] == "Alice Updated"
    assert archived["status"] == "archived"
    assert [call["method"] for call in session.calls] == ["POST", "PATCH", "POST", "DELETE"]
    assert session.calls[2]["url"] == "http://api.test/clients/1/archive"


def test_deal_routes_form_correct_requests() -> None:
    session = FakeSession(
        [
            FakeResponse(200, [{"id": 1}]),
            FakeResponse(200, {"id": 1}),
            FakeResponse(201, {"id": 2}),
            FakeResponse(200, {"id": 2}),
            FakeResponse(204, {}),
        ]
    )
    client = MiniCRMGUIAPIClient(base_url="http://api.test", session=session)

    client.list_deals(search="crm")
    client.get_deal(1)
    client.create_deal({"title": "Deal"})
    client.update_deal(2, {"status": "won"})
    client.delete_deal(2)

    assert session.calls[0]["params"] == {"limit": 100, "offset": 0, "search": "crm"}
    assert session.calls[1]["url"] == "http://api.test/deals/1"
    assert session.calls[3]["method"] == "PATCH"
    assert session.calls[4]["method"] == "DELETE"


def test_get_all_deals_uses_pagination_and_merges_all_pages() -> None:
    first_page = [{"id": index} for index in range(1, 101)]
    second_page = [{"id": index} for index in range(101, 201)]
    third_page = [{"id": index} for index in range(201, 204)]
    session = FakeSession(
        [
            FakeResponse(200, first_page),
            FakeResponse(200, second_page),
            FakeResponse(200, third_page),
        ]
    )
    client = MiniCRMGUIAPIClient(base_url="http://api.test", session=session)

    records = client.get_all_deals()

    assert len(records) == 203
    assert records[0]["id"] == 1
    assert records[-1]["id"] == 203
    assert [call["params"]["offset"] for call in session.calls] == [0, 100, 200]
    assert all(call["params"]["limit"] == 100 for call in session.calls)


def test_task_complete_reopen_and_search() -> None:
    session = FakeSession(
        [
            FakeResponse(200, [{"id": 1}]),
            FakeResponse(200, {"id": 1, "completed": True}),
            FakeResponse(200, {"id": 1, "completed": False}),
        ]
    )
    client = MiniCRMGUIAPIClient(base_url="http://api.test", session=session)

    client.list_tasks(search="follow up")
    completed = client.complete_task(1)
    reopened = client.reopen_task(1)

    assert session.calls[0]["params"] == {"limit": 100, "offset": 0, "search": "follow up"}
    assert session.calls[1]["url"] == "http://api.test/tasks/1/complete"
    assert session.calls[2]["url"] == "http://api.test/tasks/1/reopen"
    assert completed["completed"] is True
    assert reopened["completed"] is False


def test_deal_list_still_uses_single_page_limit_100() -> None:
    session = FakeSession([FakeResponse(200, [{"id": 1}])])
    client = MiniCRMGUIAPIClient(base_url="http://api.test", session=session)

    client.list_deals()

    assert session.calls == [
        {
            "method": "GET",
            "url": "http://api.test/deals",
            "params": {"limit": 100, "offset": 0},
            "json": None,
            "timeout": 10,
        }
    ]


def test_health_check_returns_boolean() -> None:
    session = FakeSession([FakeResponse(200, {"status": "ok"})])
    client = MiniCRMGUIAPIClient(base_url="http://api.test", session=session)

    assert client.check_health() is True


def test_api_errors_are_wrapped_cleanly() -> None:
    session = FakeSession([FakeResponse(422, {"detail": "bad data"})])
    client = MiniCRMGUIAPIClient(base_url="http://api.test", session=session)

    with pytest.raises(GUIAPIError, match="HTTP 422"):
        client.create_task({"title": ""})


def test_request_exception_is_wrapped() -> None:
    session = FakeSession(exception=requests.ConnectionError("offline"))
    client = MiniCRMGUIAPIClient(base_url="http://api.test", session=session)

    with pytest.raises(GUIAPIError, match="offline"):
        client.list_clients()
