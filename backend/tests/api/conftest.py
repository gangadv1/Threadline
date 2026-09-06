from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_repository
from app.database import GoalRepository, init_db
from app.main import app


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    """A TestClient wired to a throwaway SQLite file per test.

    Overriding the `get_repository` dependency (rather than mutating the
    module-level DEFAULT_DB_PATH) keeps tests isolated from each other and
    from whatever database a developer has running locally.
    """
    db_path = tmp_path / "test_threadline.db"
    init_db(db_path)

    def _override_repository() -> GoalRepository:
        return GoalRepository(db_path)

    app.dependency_overrides[get_repository] = _override_repository
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
