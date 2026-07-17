from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=False)

DEFAULT_BACKEND_URL = "http://localhost:8000"
DEFAULT_LIMIT = 100
REQUEST_TIMEOUT = 10


class GUIAPIError(RuntimeError):
    """Raised when the GUI API client cannot complete a request."""


class MiniCRMGUIAPIClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        session: requests.Session | None = None,
        request_timeout: int = REQUEST_TIMEOUT,
    ) -> None:
        self.base_url = (base_url or os.getenv("BACKEND_URL", DEFAULT_BACKEND_URL)).rstrip("/")
        self.session = session or requests.Session()
        self.request_timeout = request_timeout

    def check_health(self) -> bool:
        response = self._request("GET", "/health", error_context="Backend health check")
        try:
            payload = response.json()
        except ValueError as exc:
            raise GUIAPIError("Backend health check returned invalid JSON.") from exc
        return response.status_code == 200 and payload == {"status": "ok"}

    def list_clients(
        self,
        *,
        search: str | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params = {"limit": limit, "offset": offset}
        if search:
            params["search"] = search
        return self._request_json_list("GET", "/clients", params=params, error_context="Loading clients")

    def get_all_clients(self) -> list[dict[str, Any]]:
        return self._get_all_records("/clients", error_context="Loading all clients")

    def get_client(self, client_id: int) -> dict[str, Any]:
        return self._request_json("GET", f"/clients/{client_id}", error_context="Loading client")

    def create_client(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("POST", "/clients", json_payload=payload, error_context="Creating client")

    def update_client(self, client_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(
            "PATCH",
            f"/clients/{client_id}",
            json_payload=payload,
            error_context="Updating client",
        )

    def archive_client(self, client_id: int) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"/clients/{client_id}/archive",
            error_context="Archiving client",
        )

    def delete_client(self, client_id: int) -> None:
        self._request_no_content("DELETE", f"/clients/{client_id}", error_context="Deleting client")

    def list_deals(
        self,
        *,
        search: str | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params = {"limit": limit, "offset": offset}
        if search:
            params["search"] = search
        return self._request_json_list("GET", "/deals", params=params, error_context="Loading deals")

    def get_all_deals(self) -> list[dict[str, Any]]:
        return self._get_all_records("/deals", error_context="Loading all deals")

    def get_deal(self, deal_id: int) -> dict[str, Any]:
        return self._request_json("GET", f"/deals/{deal_id}", error_context="Loading deal")

    def create_deal(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("POST", "/deals", json_payload=payload, error_context="Creating deal")

    def update_deal(self, deal_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(
            "PATCH",
            f"/deals/{deal_id}",
            json_payload=payload,
            error_context="Updating deal",
        )

    def delete_deal(self, deal_id: int) -> None:
        self._request_no_content("DELETE", f"/deals/{deal_id}", error_context="Deleting deal")

    def list_tasks(
        self,
        *,
        search: str | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params = {"limit": limit, "offset": offset}
        if search:
            params["search"] = search
        return self._request_json_list("GET", "/tasks", params=params, error_context="Loading tasks")

    def get_task(self, task_id: int) -> dict[str, Any]:
        return self._request_json("GET", f"/tasks/{task_id}", error_context="Loading task")

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("POST", "/tasks", json_payload=payload, error_context="Creating task")

    def update_task(self, task_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(
            "PATCH",
            f"/tasks/{task_id}",
            json_payload=payload,
            error_context="Updating task",
        )

    def complete_task(self, task_id: int) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"/tasks/{task_id}/complete",
            error_context="Completing task",
        )

    def reopen_task(self, task_id: int) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"/tasks/{task_id}/reopen",
            error_context="Reopening task",
        )

    def delete_task(self, task_id: int) -> None:
        self._request_no_content("DELETE", f"/tasks/{task_id}", error_context="Deleting task")

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_payload: dict[str, Any] | None = None,
        error_context: str,
    ) -> dict[str, Any]:
        response = self._request(
            method,
            path,
            params=params,
            json_payload=json_payload,
            error_context=error_context,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise GUIAPIError(f"{error_context} returned invalid JSON.") from exc

        if not isinstance(payload, dict):
            raise GUIAPIError(f"{error_context} returned an unexpected response payload.")
        return payload

    def _request_json_list(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        error_context: str,
    ) -> list[dict[str, Any]]:
        response = self._request(method, path, params=params, error_context=error_context)
        try:
            payload = response.json()
        except ValueError as exc:
            raise GUIAPIError(f"{error_context} returned invalid JSON.") from exc

        if not isinstance(payload, list):
            raise GUIAPIError(f"{error_context} returned an unexpected response payload.")
        return payload

    def _request_no_content(self, method: str, path: str, *, error_context: str) -> None:
        self._request(method, path, error_context=error_context)

    def _get_all_records(self, path: str, *, error_context: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        offset = 0

        while True:
            page = self._request_json_list(
                "GET",
                path,
                params={"limit": DEFAULT_LIMIT, "offset": offset},
                error_context=error_context,
            )
            records.extend(page)
            if len(page) < DEFAULT_LIMIT:
                break
            offset += DEFAULT_LIMIT

        return records

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_payload: dict[str, Any] | None = None,
        error_context: str,
    ) -> requests.Response:
        try:
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                params=params,
                json=json_payload,
                timeout=self.request_timeout,
            )
        except requests.RequestException as exc:
            raise GUIAPIError(f"{error_context} failed: {exc}") from exc

        if response.status_code >= 400:
            raise GUIAPIError(
                f"{error_context} failed with HTTP {response.status_code}: {self._safe_response_body(response)}"
            )
        return response

    @staticmethod
    def _safe_response_body(response: requests.Response) -> str:
        body: str
        try:
            body = json.dumps(response.json(), ensure_ascii=True)
        except ValueError:
            body = response.text.strip() or "<empty>"
        return body[:300] + ("..." if len(body) > 300 else "")
