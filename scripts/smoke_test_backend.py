from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

import requests

DEFAULT_BACKEND_URL = "http://localhost:8000"
REQUEST_TIMEOUT = 10


def _build_backend_url() -> str:
    return os.getenv("BACKEND_URL", DEFAULT_BACKEND_URL).rstrip("/")


def _raise_for_status(response: requests.Response) -> requests.Response:
    response.raise_for_status()
    return response


def _delete_if_created(session: requests.Session, url: str, entity_id: int | None) -> None:
    if entity_id is None:
        return
    response = session.delete(f"{url}/{entity_id}", timeout=REQUEST_TIMEOUT)
    response.raise_for_status()


def run_smoke_test() -> int:
    base_url = _build_backend_url()
    unique_suffix = (
        f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    )

    client_id: int | None = None
    deal_id: int | None = None
    task_id: int | None = None
    flow_error: Exception | None = None
    cleanup_error: Exception | None = None

    with requests.Session() as session:
        try:
            health_response = _raise_for_status(
                session.get(f"{base_url}/health", timeout=REQUEST_TIMEOUT)
            )
            if health_response.json() != {"status": "ok"}:
                raise RuntimeError("Health endpoint returned an unexpected payload.")
            print("health: OK")

            created_client = _raise_for_status(
                session.post(
                    f"{base_url}/clients",
                    json={
                        "name": f"Smoke Client {unique_suffix}",
                        "company": "Stage 3B",
                        "email": f"smoke-{uuid4().hex[:8]}@example.com",
                        "phone": "+10000000000",
                    },
                    timeout=REQUEST_TIMEOUT,
                )
            ).json()
            client_id = created_client["id"]
            print(f"client create: OK ({client_id})")

            fetched_client = _raise_for_status(
                session.get(f"{base_url}/clients/{client_id}", timeout=REQUEST_TIMEOUT)
            ).json()
            if fetched_client["id"] != client_id:
                raise RuntimeError("Client lookup returned a mismatched id.")
            print("client get: OK")

            updated_client = _raise_for_status(
                session.patch(
                    f"{base_url}/clients/{client_id}",
                    json={"company": "Stage 3B Updated"},
                    timeout=REQUEST_TIMEOUT,
                )
            ).json()
            if updated_client["company"] != "Stage 3B Updated":
                raise RuntimeError("Client patch verification failed.")
            print("client patch: OK")

            created_deal = _raise_for_status(
                session.post(
                    f"{base_url}/deals",
                    json={
                        "title": f"Smoke Deal {unique_suffix}",
                        "client_id": client_id,
                        "amount": 1234.5,
                        "status": "in_progress",
                    },
                    timeout=REQUEST_TIMEOUT,
                )
            ).json()
            deal_id = created_deal["id"]
            print(f"deal create: OK ({deal_id})")

            fetched_deal = _raise_for_status(
                session.get(f"{base_url}/deals/{deal_id}", timeout=REQUEST_TIMEOUT)
            ).json()
            if fetched_deal["client_id"] != client_id:
                raise RuntimeError("Deal lookup returned an unexpected client_id.")
            print("deal get: OK")

            created_task = _raise_for_status(
                session.post(
                    f"{base_url}/tasks",
                    json={
                        "title": f"Smoke Task {unique_suffix}",
                        "description": "Container smoke test task",
                        "client_id": client_id,
                        "deal_id": deal_id,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
            ).json()
            task_id = created_task["id"]
            print(f"task create: OK ({task_id})")

            fetched_task = _raise_for_status(
                session.get(f"{base_url}/tasks/{task_id}", timeout=REQUEST_TIMEOUT)
            ).json()
            if fetched_task["deal_id"] != deal_id or fetched_task["client_id"] != client_id:
                raise RuntimeError("Task lookup returned unexpected relation ids.")
            print("task get: OK")

            completed_task = _raise_for_status(
                session.post(
                    f"{base_url}/tasks/{task_id}/complete",
                    timeout=REQUEST_TIMEOUT,
                )
            ).json()
            if completed_task["completed"] is not True:
                raise RuntimeError("Task complete endpoint did not mark the task completed.")
            print("task complete: OK")
        except Exception as error:
            flow_error = error

        try:
            _delete_if_created(session, f"{base_url}/tasks", task_id)
            _delete_if_created(session, f"{base_url}/deals", deal_id)
            _delete_if_created(session, f"{base_url}/clients", client_id)
            print("cleanup: OK")
        except Exception as error:
            cleanup_error = error

    if cleanup_error and flow_error:
        raise flow_error from cleanup_error
    if cleanup_error:
        raise cleanup_error
    if flow_error:
        raise flow_error

    return 0


def main() -> int:
    try:
        return run_smoke_test()
    except Exception as error:
        print(f"Smoke test failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
