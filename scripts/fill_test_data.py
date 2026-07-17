from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import requests
from dotenv import load_dotenv
from faker import Faker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=False)

DEFAULT_BACKEND_URL = "http://localhost:8000"
DEFAULT_COUNT = 1000
DEFAULT_SEED = 42
REQUEST_TIMEOUT = 10
PROGRESS_INTERVAL = 100

CLIENT_STATUS_WEIGHTS = (0.88, 0.12)
DEAL_STATUS_WEIGHTS = (0.32, 0.38, 0.20, 0.10)
TASK_RELATION_WEIGHTS = (0.45, 0.22, 0.23, 0.10)

DEAL_SERVICE_TYPES = (
    "CRM rollout",
    "Sales analytics",
    "Lead qualification",
    "Pipeline audit",
    "Account expansion",
    "Retention campaign",
    "Support retainer",
    "Revenue dashboard",
)
DEAL_SCOPE_TYPES = (
    "Implementation",
    "Optimization",
    "Migration",
    "Discovery",
    "Expansion",
    "Quarterly",
    "Annual",
)
TASK_ACTIONS = (
    "Call",
    "Email",
    "Prepare",
    "Review",
    "Coordinate",
    "Schedule",
    "Draft",
    "Confirm",
)
TASK_OBJECTS = (
    "kickoff agenda",
    "proposal follow-up",
    "renewal notes",
    "pricing options",
    "next-step summary",
    "implementation checklist",
    "commercial offer",
    "stakeholder update",
)
TASK_DESCRIPTION_TEMPLATES = (
    "Follow up with {target} about the {topic}.",
    "Prepare materials for {target} regarding the {topic}.",
    "Confirm internal next steps for {target} before the {topic}.",
    "Document the latest discussion with {target} for the {topic}.",
)


class SeedDataError(RuntimeError):
    """Raised when the seed generator cannot complete successfully."""


@dataclass(frozen=True)
class FillTestDataConfig:
    clients: int
    deals: int
    tasks: int
    seed: int
    base_url: str
    run_identifier: str
    request_timeout: int = REQUEST_TIMEOUT
    progress_interval: int = PROGRESS_INTERVAL


@dataclass(frozen=True)
class GenerationSummary:
    clients_created: int
    deals_created: int
    tasks_created: int

    @property
    def total_created(self) -> int:
        return self.clients_created + self.deals_created + self.tasks_created


@dataclass(frozen=True)
class CreatedClient:
    id: int
    name: str
    company: str | None
    email: str
    status: str


@dataclass(frozen=True)
class CreatedDeal:
    id: int
    title: str
    client_id: int | None
    status: str


@dataclass(frozen=True)
class CreatedTask:
    id: int
    title: str
    client_id: int | None
    deal_id: int | None
    completed: bool


def _non_negative_int(value: str) -> int:
    parsed_value = int(value)
    if parsed_value < 0:
        raise argparse.ArgumentTypeError("Counts must be non-negative integers.")
    return parsed_value


def build_run_identifier() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{timestamp}-{uuid4().hex[:6]}"


def get_default_base_url() -> str:
    return os.getenv("BACKEND_URL", DEFAULT_BACKEND_URL).rstrip("/")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fill the running Mini CRM backend with realistic seed data via HTTP API.",
    )
    parser.add_argument("--clients", type=_non_negative_int, default=DEFAULT_COUNT)
    parser.add_argument("--deals", type=_non_negative_int, default=DEFAULT_COUNT)
    parser.add_argument("--tasks", type=_non_negative_int, default=DEFAULT_COUNT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--base-url", default=get_default_base_url())
    return parser.parse_args(argv)


def build_config(
    argv: list[str] | None = None,
    *,
    run_identifier: str | None = None,
) -> FillTestDataConfig:
    args = parse_args(argv)
    return FillTestDataConfig(
        clients=args.clients,
        deals=args.deals,
        tasks=args.tasks,
        seed=args.seed,
        base_url=args.base_url.rstrip("/"),
        run_identifier=run_identifier or build_run_identifier(),
    )


def _slugify_name(name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", ".", name.lower()).strip(".")
    return normalized or "contact"


class FillTestDataRunner:
    def __init__(self, config: FillTestDataConfig, session: requests.Session) -> None:
        self.config = config
        self.session = session
        self.faker = Faker()
        self.faker.seed_instance(config.seed)
        self.random = random.Random(config.seed)

        self.clients: list[CreatedClient] = []
        self.clients_by_id: dict[int, CreatedClient] = {}
        self.deals: list[CreatedDeal] = []
        self.deals_by_id: dict[int, CreatedDeal] = {}
        self.tasks: list[CreatedTask] = []

    def run(self) -> GenerationSummary:
        self.check_health()
        self.create_clients()
        self.create_deals()
        self.create_tasks()

        summary = GenerationSummary(
            clients_created=len(self.clients),
            deals_created=len(self.deals),
            tasks_created=len(self.tasks),
        )
        print(f"Clients created: {summary.clients_created}")
        print(f"Deals created: {summary.deals_created}")
        print(f"Tasks created: {summary.tasks_created}")
        print(f"Total created: {summary.total_created}")
        return summary

    def check_health(self) -> None:
        health_url = f"{self.config.base_url}/health"
        try:
            response = self.session.request(
                "GET",
                health_url,
                timeout=self.config.request_timeout,
            )
        except requests.RequestException as exc:
            raise SeedDataError(
                f"Backend is unavailable at {health_url}: {exc}"
            ) from exc

        if response.status_code != 200:
            raise SeedDataError(
                "Backend health check failed with "
                f"HTTP {response.status_code}: {self._safe_response_body(response)}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise SeedDataError("Backend health check returned invalid JSON.") from exc

        if payload != {"status": "ok"}:
            raise SeedDataError(
                f"Backend health check returned unexpected payload: {payload!r}"
            )

        print("health: OK")

    def create_clients(self) -> None:
        for ordinal in range(1, self.config.clients + 1):
            payload = self.build_client_payload(ordinal)
            response_payload = self._request_json(
                "POST",
                "/clients",
                json_payload=payload,
                error_context=f"Client #{ordinal}",
            )
            created_client = CreatedClient(
                id=response_payload["id"],
                name=response_payload["name"],
                company=response_payload.get("company"),
                email=response_payload["email"],
                status=response_payload["status"],
            )
            self.clients.append(created_client)
            self.clients_by_id[created_client.id] = created_client
            self._print_progress("Clients", ordinal, self.config.clients)

    def create_deals(self) -> None:
        for ordinal in range(1, self.config.deals + 1):
            payload = self.build_deal_payload(ordinal)
            response_payload = self._request_json(
                "POST",
                "/deals",
                json_payload=payload,
                error_context=f"Deal #{ordinal}",
            )
            created_deal = CreatedDeal(
                id=response_payload["id"],
                title=response_payload["title"],
                client_id=response_payload.get("client_id"),
                status=response_payload["status"],
            )
            self.deals.append(created_deal)
            self.deals_by_id[created_deal.id] = created_deal
            self._print_progress("Deals", ordinal, self.config.deals)

    def create_tasks(self) -> None:
        for ordinal in range(1, self.config.tasks + 1):
            payload, should_complete = self.build_task_payload(ordinal)
            response_payload = self._request_json(
                "POST",
                "/tasks",
                json_payload=payload,
                error_context=f"Task #{ordinal}",
            )

            if should_complete:
                response_payload = self._request_json(
                    "POST",
                    f"/tasks/{response_payload['id']}/complete",
                    error_context=f"Task #{ordinal} completion",
                )

            created_task = CreatedTask(
                id=response_payload["id"],
                title=response_payload["title"],
                client_id=response_payload.get("client_id"),
                deal_id=response_payload.get("deal_id"),
                completed=response_payload["completed"],
            )
            self.tasks.append(created_task)
            self._print_progress("Tasks", ordinal, self.config.tasks)

    def build_client_payload(self, ordinal: int) -> dict[str, object]:
        name = self.faker.name()
        company = None if self.random.random() < 0.22 else self.faker.company()
        phone = None if self.random.random() < 0.28 else self._clean_phone(self.faker.phone_number())
        status = self.random.choices(
            ["active", "archived"],
            weights=CLIENT_STATUS_WEIGHTS,
            k=1,
        )[0]
        domain = self.faker.free_email_domain()
        email = f"{_slugify_name(name)}.{ordinal:04d}.{self.config.run_identifier}@{domain}"

        return {
            "name": name,
            "company": company,
            "email": email,
            "phone": phone,
            "status": status,
        }

    def build_deal_payload(self, ordinal: int) -> dict[str, object]:
        linked_client = None
        if self.clients and self.random.random() < 0.86:
            linked_client = self.random.choice(self.clients)

        service_type = self.random.choice(DEAL_SERVICE_TYPES)
        scope_type = self.random.choice(DEAL_SCOPE_TYPES)
        target_name = (
            linked_client.company
            or linked_client.name.split()[0]
            if linked_client is not None
            else self.faker.company()
        )
        title = f"{scope_type} {service_type} for {target_name}"
        status = self.random.choices(
            ["new", "in_progress", "won", "lost"],
            weights=DEAL_STATUS_WEIGHTS,
            k=1,
        )[0]

        return {
            "title": title,
            "client_id": linked_client.id if linked_client is not None else None,
            "amount": round(self.random.triangular(800, 85000, 12000), 2),
            "status": status,
            "expected_close_date": self._build_expected_close_date(status, ordinal),
        }

    def build_task_payload(self, ordinal: int) -> tuple[dict[str, object], bool]:
        relation_mode = self._select_task_relation_mode(ordinal)
        client_id: int | None = None
        deal_id: int | None = None

        if relation_mode == "both" and self.deals:
            deal = self._choose_deal(prefer_client_linked=True)
            deal_id = deal.id
            if deal.client_id is not None:
                client_id = deal.client_id
            elif self.clients:
                client_id = self.random.choice(self.clients).id
        elif relation_mode == "client_only" and self.clients:
            client_id = self.random.choice(self.clients).id
        elif relation_mode == "deal_only" and self.deals:
            deal = self._choose_deal(prefer_client_linked=False)
            deal_id = deal.id

        should_complete = self.random.random() < 0.34
        title = f"{self.random.choice(TASK_ACTIONS)} {self.random.choice(TASK_OBJECTS)}"
        description = self._build_task_description(client_id, deal_id)

        return (
            {
                "title": title,
                "description": description,
                "client_id": client_id,
                "deal_id": deal_id,
                "due_date": self._build_due_date(should_complete, ordinal),
            },
            should_complete,
        )

    def _build_task_description(
        self,
        client_id: int | None,
        deal_id: int | None,
    ) -> str:
        if client_id is not None:
            client_label = self.clients_by_id[client_id].company or self.clients_by_id[client_id].name
        else:
            client_label = self.faker.company()

        if deal_id is not None:
            topic = self.deals_by_id[deal_id].title.lower()
        else:
            topic = self.random.choice(TASK_OBJECTS)

        template = self.random.choice(TASK_DESCRIPTION_TEMPLATES)
        return template.format(target=client_label, topic=topic)

    def _build_expected_close_date(self, status: str, ordinal: int) -> str | None:
        if status in {"new", "in_progress"}:
            if self.random.random() < 0.15:
                return None
            return self.faker.date_between(start_date="+7d", end_date="+180d").isoformat()

        if ordinal % 4 == 0 or self.random.random() < 0.65:
            return self.faker.date_between(start_date="-180d", end_date="+10d").isoformat()
        return None

    def _build_due_date(self, completed: bool, ordinal: int) -> str | None:
        if ordinal % 7 == 0 and self.random.random() < 0.4:
            return None

        if completed:
            return self.faker.date_between(start_date="-45d", end_date="+2d").isoformat()
        return self.faker.date_between(start_date="-2d", end_date="+45d").isoformat()

    def _select_task_relation_mode(self, ordinal: int) -> str:
        available_modes: list[str] = []
        if self.deals and any(deal.client_id is not None for deal in self.deals):
            available_modes.append("both")
        if self.clients:
            available_modes.append("client_only")
        if self.deals:
            available_modes.append("deal_only")
        available_modes.append("none")

        if ordinal <= len(available_modes):
            return available_modes[ordinal - 1]

        weights_by_mode = {
            "both": TASK_RELATION_WEIGHTS[0],
            "client_only": TASK_RELATION_WEIGHTS[1],
            "deal_only": TASK_RELATION_WEIGHTS[2],
            "none": TASK_RELATION_WEIGHTS[3],
        }
        weights = [weights_by_mode[mode] for mode in available_modes]
        return self.random.choices(available_modes, weights=weights, k=1)[0]

    def _choose_deal(self, *, prefer_client_linked: bool) -> CreatedDeal:
        if prefer_client_linked:
            client_linked_deals = [deal for deal in self.deals if deal.client_id is not None]
            if client_linked_deals:
                return self.random.choice(client_linked_deals)
        else:
            unlinked_deals = [deal for deal in self.deals if deal.client_id is None]
            if unlinked_deals:
                return self.random.choice(unlinked_deals)
        return self.random.choice(self.deals)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, object] | None = None,
        error_context: str,
    ) -> dict[str, object]:
        url = f"{self.config.base_url}{path}"
        try:
            response = self.session.request(
                method,
                url,
                json=json_payload,
                timeout=self.config.request_timeout,
            )
        except requests.RequestException as exc:
            raise SeedDataError(f"{error_context} request failed: {exc}") from exc

        if response.status_code >= 400:
            raise SeedDataError(
                f"{error_context} failed with HTTP {response.status_code}: "
                f"{self._safe_response_body(response)}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise SeedDataError(f"{error_context} returned invalid JSON.") from exc

        if not isinstance(payload, dict):
            raise SeedDataError(f"{error_context} returned unexpected response payload.")
        return payload

    def _print_progress(self, label: str, current: int, total: int) -> None:
        if total == 0:
            return
        if current % self.config.progress_interval == 0 or current == total:
            print(f"{label} progress: {current}/{total}")

    @staticmethod
    def _clean_phone(value: str) -> str:
        return " ".join(value.split())

    @staticmethod
    def _safe_response_body(response: requests.Response) -> str:
        body: str
        try:
            body = json.dumps(response.json(), ensure_ascii=True)
        except ValueError:
            body = response.text.strip() or "<empty>"
        return body[:300] + ("..." if len(body) > 300 else "")


def run_fill_test_data(
    config: FillTestDataConfig,
    session: requests.Session,
) -> GenerationSummary:
    runner = FillTestDataRunner(config, session)
    return runner.run()


def main(argv: list[str] | None = None) -> int:
    config = build_config(argv)
    try:
        with requests.Session() as session:
            run_fill_test_data(config, session)
    except SeedDataError as error:
        print(f"Seed data generation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
