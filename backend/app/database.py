"""SQLite persistence for AdministrativeGoal workflow state.

Goals are stored as serialized JSON rather than mapped across many
relational tables. The `AdministrativeGoal` model (and everything nested
inside it - tasks, risks, proposed actions, documents) is already the
single source of truth for shape and validation, so persistence just
needs to save and reload that JSON faithfully. This keeps the storage
layer thin and avoids a second, parallel schema that could drift from
the Pydantic models Member 1 already built.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.models import AdministrativeGoal

DEFAULT_DB_PATH = Path(os.environ.get("THREADLINE_DB_PATH", "threadline.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def get_connection(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    """Create the goals table if it does not already exist."""
    with get_connection(db_path) as connection:
        connection.execute(_SCHEMA)
        connection.commit()


class GoalRepository:
    """Thin data-access layer around the `goals` table.

    A repository object is created per-request (see `app/api/dependencies.py`)
    so each request gets its own SQLite connection; SQLite connections are not
    safe to share across threads/requests in FastAPI's default threadpool.
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self._db_path = db_path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = get_connection(self._db_path)
        try:
            yield connection
        finally:
            connection.close()

    def save(self, goal: AdministrativeGoal) -> AdministrativeGoal:
        """Insert or fully replace the stored state for a goal."""
        payload = goal.model_dump_json()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO goals (id, title, status, data, created_at, updated_at)
                VALUES (:id, :title, :status, :data, :created_at, :updated_at)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    status = excluded.status,
                    data = excluded.data,
                    updated_at = excluded.updated_at
                """,
                {
                    "id": goal.id,
                    "title": goal.title,
                    "status": goal.status.value,
                    "data": payload,
                    "created_at": goal.created_at.isoformat(),
                    "updated_at": goal.updated_at.isoformat(),
                },
            )
            connection.commit()
        return goal

    def get(self, goal_id: str) -> AdministrativeGoal | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT data FROM goals WHERE id = ?", (goal_id,)
            ).fetchone()
        if row is None:
            return None
        return AdministrativeGoal.model_validate_json(row["data"])

    def list_all(self) -> list[AdministrativeGoal]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT data FROM goals ORDER BY updated_at DESC"
            ).fetchall()
        return [AdministrativeGoal.model_validate_json(row["data"]) for row in rows]

    def delete(self, goal_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
            connection.commit()
        return cursor.rowcount > 0
