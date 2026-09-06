from __future__ import annotations

from fastapi import HTTPException, status

from app.database import DEFAULT_DB_PATH, GoalRepository
from app.models import AdministrativeGoal


def get_repository() -> GoalRepository:
    """Provide a per-request GoalRepository.

    Overridden in tests to point at a temporary database file.
    """
    return GoalRepository(DEFAULT_DB_PATH)


def get_goal_or_404(goal_id: str, repository: GoalRepository) -> AdministrativeGoal:
    goal = repository.get(goal_id)
    if goal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Goal '{goal_id}' was not found.",
        )
    return goal
