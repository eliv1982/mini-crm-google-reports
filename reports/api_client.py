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
DEFAULT_PAGE_LIMIT = 100
REQUEST_TIMEOUT = 10


class CRMAPIError(RuntimeError):
    """Raised when the CRM API cannot be queried successfully."""


class CRMAPIClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        session: requests.Session | None = None,
        page_limit: int = DEFAULT_PAGE_LIMIT,
        request_timeout: int = REQUEST_TIMEOUT,
    ) -> None:
        self.base_url = (base_url or os.getenv("BACKEND_URL", DEFAULT_BACKEND_URL)).rstrip("/")
        self.session = session or requests.Session()
        self.page_limit = page_limit
        self.request_timeout = request_timeout

    def check_health(self) -> None:
        try:
            response = self.session.request(
                "GET",
                f"{self.base_url}/health",
                timeout=self.request_timeout,
            )
        except requests.RequestException as exc:
            raise CRMAPIError(
                f"CRM API health check failed: {self._describe_request_error(exc)}"
            ) from exc

        if response.status_code != 200:
            raise CRMAPIError(
                "CRM API health check returned "
                f"HTTP {response.status_code}: {self._safe_response_body(response)}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise CRMAPIError("CRM API health check returned invalid JSON.") from exc

        if payload != {"status": "ok"}:
            raise CRMAPIError(f"CRM API health check returned unexpected payload: {payload!r}")

    def get_all_clients(self) -> list[dict[str, Any]]:
        return self._get_all_records("/clients")

    def get_all_deals(self) -> list[dict[str, Any]]:
        return self._get_all_records("/deals")

    def get_all_tasks(self) -> list[dict[str, Any]]:
        return self._get_all_records("/tasks")

    def _get_all_records(self, path: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        offset = 0

        while True:
            try:
                response = self.session.request(
                    "GET",
                    f"{self.base_url}{path}",
                    params={"limit": self.page_limit, "offset": offset},
                    timeout=self.request_timeout,
                )
            except requests.RequestException as exc:
                raise CRMAPIError(
                    f"Failed to fetch {path}: {self._describe_request_error(exc)}"
                ) from exc

            if response.status_code >= 400:
                raise CRMAPIError(
                    f"Failed to fetch {path} at offset {offset}: "
                    f"HTTP {response.status_code}: {self._safe_response_body(response)}"
                )

            try:
                page = response.json()
            except ValueError as exc:
                raise CRMAPIError(f"Failed to decode JSON from {path} at offset {offset}.") from exc

            if not isinstance(page, list):
                raise CRMAPIError(
                    f"Expected a list response from {path} at offset {offset}, got {type(page).__name__}."
                )

            records.extend(page)
            if len(page) < self.page_limit:
                break
            offset += self.page_limit

        return records

    def _describe_request_error(self, exc: requests.RequestException) -> str:
        # str(exc) embeds urllib3 internals and localized OS text; the original
        # exception stays available through exception chaining.
        if isinstance(exc, requests.Timeout):
            return f"request to {self.base_url} timed out"
        if isinstance(exc, requests.ConnectionError):
            return f"could not connect to {self.base_url}"
        return f"{type(exc).__name__} while contacting {self.base_url}"

    @staticmethod
    def _safe_response_body(response: requests.Response) -> str:
        body: str
        try:
            body = json.dumps(response.json(), ensure_ascii=True)
        except ValueError:
            body = response.text.strip() or "<empty>"
        return body[:300] + ("..." if len(body) > 300 else "")
