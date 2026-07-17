from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from typing import Any


def compute_clients_analytics(clients: list[dict[str, Any]]) -> dict[str, Any]:
    total_clients = len(clients)
    active_clients = sum(1 for client in clients if client.get("status") == "active")
    archived_clients = sum(1 for client in clients if client.get("status") == "archived")
    clients_with_company = sum(1 for client in clients if _has_text(client.get("company")))
    clients_without_company = total_clients - clients_with_company

    company_counts = Counter(
        str(client.get("company")).strip()
        for client in clients
        if _has_text(client.get("company"))
    )
    if company_counts:
        company_name, company_count = company_counts.most_common(1)[0]
    else:
        company_name, company_count = None, 0

    return {
        "total_clients": total_clients,
        "active_clients": active_clients,
        "archived_clients": archived_clients,
        "clients_with_company": clients_with_company,
        "clients_without_company": clients_without_company,
        "most_common_company": {"company": company_name, "count": company_count},
        "percentage_active": _percentage(active_clients, total_clients),
    }


def compute_deals_analytics(deals: list[dict[str, Any]]) -> dict[str, Any]:
    total_deals = len(deals)
    total_amount = sum(_to_float(deal.get("amount")) for deal in deals)
    status_counts = {
        "new": sum(1 for deal in deals if deal.get("status") == "new"),
        "in_progress": sum(1 for deal in deals if deal.get("status") == "in_progress"),
        "won": sum(1 for deal in deals if deal.get("status") == "won"),
        "lost": sum(1 for deal in deals if deal.get("status") == "lost"),
    }
    won_deals = [deal for deal in deals if deal.get("status") == "won"]
    won_amount = sum(_to_float(deal.get("amount")) for deal in won_deals)
    deals_with_client = sum(1 for deal in deals if deal.get("client_id") is not None)

    return {
        "total_deals": total_deals,
        "total_amount": total_amount,
        "average_amount": (total_amount / total_deals) if total_deals else 0.0,
        "status_counts": status_counts,
        "won_amount": won_amount,
        "average_won_amount": (won_amount / len(won_deals)) if won_deals else 0.0,
        "deals_with_client": deals_with_client,
        "deals_without_client": total_deals - deals_with_client,
    }


def compute_tasks_analytics(
    tasks: list[dict[str, Any]],
    *,
    today: date | None = None,
) -> dict[str, Any]:
    resolved_today = today or date.today()
    total_tasks = len(tasks)
    completed_tasks = sum(1 for task in tasks if bool(task.get("completed")))
    open_tasks = total_tasks - completed_tasks
    overdue_open_tasks = 0

    for task in tasks:
        if bool(task.get("completed")):
            continue
        due_date = _parse_iso_date(task.get("due_date"))
        if due_date is not None and due_date < resolved_today:
            overdue_open_tasks += 1

    tasks_with_client = sum(1 for task in tasks if task.get("client_id") is not None)
    tasks_with_deal = sum(1 for task in tasks if task.get("deal_id") is not None)
    tasks_without_links = sum(
        1
        for task in tasks
        if task.get("client_id") is None and task.get("deal_id") is None
    )

    return {
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "open_tasks": open_tasks,
        "completion_percentage": _percentage(completed_tasks, total_tasks),
        "overdue_open_tasks": overdue_open_tasks,
        "tasks_with_client": tasks_with_client,
        "tasks_with_deal": tasks_with_deal,
        "tasks_without_links": tasks_without_links,
    }


def _percentage(part: int, whole: int) -> float:
    if whole == 0:
        return 0.0
    return (part / whole) * 100


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None

    normalized_value = value.strip()
    if not normalized_value:
        return None

    try:
        return date.fromisoformat(normalized_value)
    except ValueError:
        pass

    try:
        return datetime.fromisoformat(normalized_value.replace("Z", "+00:00")).date()
    except ValueError:
        return None
