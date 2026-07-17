from __future__ import annotations

from datetime import date

from reports.analytics import (
    compute_clients_analytics,
    compute_deals_analytics,
    compute_tasks_analytics,
)


def test_compute_clients_analytics_metrics() -> None:
    analytics = compute_clients_analytics(
        [
            {"status": "active", "company": "Acme"},
            {"status": "archived", "company": "Acme"},
            {"status": "active", "company": None},
            {"status": "active", "company": "Beta"},
        ]
    )

    assert analytics["total_clients"] == 4
    assert analytics["active_clients"] == 3
    assert analytics["archived_clients"] == 1
    assert analytics["clients_with_company"] == 3
    assert analytics["clients_without_company"] == 1
    assert analytics["most_common_company"] == {"company": "Acme", "count": 2}
    assert analytics["percentage_active"] == 75.0


def test_compute_deals_analytics_amounts_and_status_counts() -> None:
    analytics = compute_deals_analytics(
        [
            {"amount": 100.0, "status": "won", "client_id": 1},
            {"amount": 250.0, "status": "new", "client_id": None},
            {"amount": 50.0, "status": "won", "client_id": 2},
            {"amount": 600.0, "status": "lost", "client_id": 3},
        ]
    )

    assert analytics["total_deals"] == 4
    assert analytics["total_amount"] == 1000.0
    assert analytics["average_amount"] == 250.0
    assert analytics["average_amount"] != analytics["total_amount"]
    assert analytics["status_counts"] == {
        "new": 1,
        "in_progress": 0,
        "won": 2,
        "lost": 1,
    }
    assert analytics["won_amount"] == 150.0
    assert analytics["average_won_amount"] == 75.0
    assert analytics["deals_with_client"] == 3
    assert analytics["deals_without_client"] == 1


def test_compute_tasks_analytics_completion_and_overdue() -> None:
    analytics = compute_tasks_analytics(
        [
            {"completed": True, "due_date": "2026-07-10", "client_id": 1, "deal_id": 2},
            {"completed": False, "due_date": "2026-07-10", "client_id": 1, "deal_id": None},
            {"completed": False, "due_date": "2026-07-20", "client_id": None, "deal_id": 3},
            {"completed": False, "due_date": "invalid-date", "client_id": None, "deal_id": None},
        ],
        today=date(2026, 7, 17),
    )

    assert analytics["total_tasks"] == 4
    assert analytics["completed_tasks"] == 1
    assert analytics["open_tasks"] == 3
    assert analytics["completion_percentage"] == 25.0
    assert analytics["overdue_open_tasks"] == 1
    assert analytics["tasks_with_client"] == 2
    assert analytics["tasks_with_deal"] == 2
    assert analytics["tasks_without_links"] == 1


def test_analytics_handle_empty_and_null_datasets() -> None:
    client_analytics = compute_clients_analytics([])
    deal_analytics = compute_deals_analytics([{"amount": None, "status": "in_progress", "client_id": None}])
    task_analytics = compute_tasks_analytics(
        [{"completed": False, "due_date": None, "client_id": None, "deal_id": None}],
        today=date(2026, 7, 17),
    )

    assert client_analytics["total_clients"] == 0
    assert client_analytics["percentage_active"] == 0.0
    assert client_analytics["most_common_company"] == {"company": None, "count": 0}

    assert deal_analytics["total_amount"] == 0.0
    assert deal_analytics["average_amount"] == 0.0
    assert deal_analytics["status_counts"]["in_progress"] == 1

    assert task_analytics["overdue_open_tasks"] == 0
    assert task_analytics["tasks_without_links"] == 1
