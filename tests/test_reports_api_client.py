from __future__ import annotations

import pytest
import requests

from reports.api_client import CRMAPIClient, CRMAPIError


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
            raise AssertionError("No fake response left for request.")
        return self.responses.pop(0)


def test_health_check_passes() -> None:
    session = FakeSession([FakeResponse(200, {"status": "ok"})])
    client = CRMAPIClient(base_url="http://api.test", session=session)

    client.check_health()

    assert session.calls[0]["url"] == "http://api.test/health"


def test_get_all_clients_uses_pagination_beyond_100() -> None:
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
    client = CRMAPIClient(base_url="http://api.test", session=session)

    records = client.get_all_clients()

    assert len(records) == 205
    assert [call["params"]["offset"] for call in session.calls] == [0, 100, 200]
    assert all(call["params"]["limit"] == 100 for call in session.calls)


def test_get_all_deals_stops_on_partial_last_page() -> None:
    session = FakeSession(
        [
            FakeResponse(200, [{"id": 1}, {"id": 2}]),
        ]
    )
    client = CRMAPIClient(base_url="http://api.test", session=session)

    records = client.get_all_deals()

    assert records == [{"id": 1}, {"id": 2}]
    assert len(session.calls) == 1


def test_get_all_tasks_handles_empty_dataset() -> None:
    session = FakeSession([FakeResponse(200, [])])
    client = CRMAPIClient(base_url="http://api.test", session=session)

    records = client.get_all_tasks()

    assert records == []


def test_api_client_raises_on_api_error() -> None:
    session = FakeSession([FakeResponse(500, {"detail": "boom"})])
    client = CRMAPIClient(base_url="http://api.test", session=session)

    with pytest.raises(CRMAPIError, match="HTTP 500"):
        client.get_all_clients()


def test_api_client_raises_on_health_request_failure() -> None:
    session = FakeSession(exception=requests.ConnectionError("offline"))
    client = CRMAPIClient(base_url="http://api.test", session=session)

    with pytest.raises(CRMAPIError, match="health check failed"):
        client.check_health()


@pytest.mark.parametrize(
    ("raised", "expected_text"),
    [
        (
            requests.ConnectionError(
                "HTTPConnectionPool(host='api.test'): Max retries exceeded "
                "(Caused by NewConnectionError('<urllib3.connection.HTTPConnection object at 0x1>'))"
            ),
            "could not connect to http://api.test",
        ),
        (requests.Timeout("read timed out"), "http://api.test timed out"),
        (requests.TooManyRedirects("loop"), "TooManyRedirects while contacting http://api.test"),
    ],
)
@pytest.mark.parametrize("operation", ["check_health", "get_all_clients"])
def test_request_failures_produce_concise_message_and_keep_original_as_cause(
    raised: Exception, expected_text: str, operation: str
) -> None:
    client = CRMAPIClient(base_url="http://api.test", session=FakeSession(exception=raised))

    with pytest.raises(CRMAPIError) as exc_info:
        getattr(client, operation)()

    message = str(exc_info.value)
    assert expected_text in message
    assert "urllib3" not in message
    assert "Max retries" not in message
    assert exc_info.value.__cause__ is raised
