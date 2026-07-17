from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.database import initialize_database
from backend.main import create_app


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "crm-test.db"


@pytest.fixture
def initialized_database_path(database_path: Path) -> Path:
    initialize_database(database_path)
    return database_path


@pytest.fixture
def client(initialized_database_path: Path) -> TestClient:
    app = create_app(database_path=initialized_database_path)
    with TestClient(app) as test_client:
        yield test_client
