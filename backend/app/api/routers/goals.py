from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_goal_or_404, get_repository
from app.api.schemas import GoalSummary, GoalUpdateRequest, TaskStatusUpdateRequest
from app.database import GoalRepository
from app.models import AdministrativeGoal

router = APIRouter(prefix="/goals", tags=["goals"])


def _summarize(goal: AdministrativeGoal) -> GoalSummary:
    return GoalSummary(
        id=goal.id,
        title=goal.title,
        status=goal.status,
        final_deadline=goal.final_deadline,
        next_action_summary=goal.next_action_summary,
        task_count=len(goal.tasks),
        open_risk_count=sum(1 for risk in goal.risks if not risk.resolved),
        updated_at=goal.updated_at,
    )


@router.post("", response_model=AdministrativeGoal, status_code=status.HTTP_201_CREATED)
def create_goal(
    goal: AdministrativeGoal,
    repository: GoalRepository = Depends(get_repository),
) -> AdministrativeGoal:
    """Store a goal produced by document extraction (or created manually).

    This only persists the goal as submitted. Run POST /goals/{id}/cycle
    afterwards to generate the ordered plan, feasibility report and action
    proposals.
    """
    existing = repository.get(goal.id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Goal '{goal.id}' already exists.",
        )
    return repository.save(goal)


@router.get("", response_model=list[GoalSummary])
def list_goals(repository: GoalRepository = Depends(get_repository)) -> list[GoalSummary]:
    return [_summarize(goal) for goal in repository.list_all()]


@router.get("/{goal_id}", response_model=AdministrativeGoal)
def get_goal(
    goal_id: str, repository: GoalRepository = Depends(get_repository)
) -> AdministrativeGoal:
    return get_goal_or_404(goal_id, repository)


@router.patch("/{goal_id}", response_model=AdministrativeGoal)
def update_goal(
    goal_id: str,
    update: GoalUpdateRequest,
    repository: GoalRepository = Depends(get_repository),
) -> AdministrativeGoal:
    """Directly correct one or more goal-level fields (title, description,
    final_deadline, status).

    Run POST /goals/{goal_id}/cycle afterwards to re-check feasibility if
    you changed final_deadline.
    """
    if update.is_empty():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least one field to update.",
        )
    goal = get_goal_or_404(goal_id, repository)
    updated_goal = goal.model_copy(deep=True)
    if update.title is not None:
        updated_goal.title = update.title
    if update.description is not None:
        updated_goal.description = update.description
    if update.final_deadline is not None:
        updated_goal.final_deadline = update.final_deadline
    if update.status is not None:
        updated_goal.status = update.status
    updated_goal.updated_at = datetime.now(timezone.utc)
    return repository.save(updated_goal)


@router.patch("/{goal_id}/tasks/{task_id}", response_model=AdministrativeGoal)
def update_task_status(
    goal_id: str,
    task_id: str,
    update: TaskStatusUpdateRequest,
    repository: GoalRepository = Depends(get_repository),
) -> AdministrativeGoal:
    """Directly correct a task's status/deadline without running replanning.

    For a disruption that should propagate to downstream tasks (a rejection,
    a delay, etc.), use POST /goals/{goal_id}/disruption instead - that path
    runs the replanner and re-analyses feasibility.
    """
    if update.is_empty():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least one of 'status' or 'deadline' to update.",
        )
    goal = get_goal_or_404(goal_id, repository)
    updated_goal = goal.model_copy(deep=True)
    task = next((item for item in updated_goal.tasks if item.id == task_id), None)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' was not found in goal '{goal_id}'.",
        )

    if update.status is not None:
        task.status = update.status
    if update.deadline is not None:
        task.deadline = update.deadline
    task.updated_at = datetime.now(timezone.utc)
    updated_goal.updated_at = datetime.now(timezone.utc)

    return repository.save(updated_goal)
