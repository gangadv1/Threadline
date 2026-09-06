from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.agents import review_action_proposal
from app.api.dependencies import get_goal_or_404, get_repository
from app.api.schemas import ActionReviewRequest
from app.database import GoalRepository
from app.models import AdministrativeGoal

router = APIRouter(prefix="/goals", tags=["actions"])


@router.post("/{goal_id}/actions/{action_id}/review", response_model=AdministrativeGoal)
def review_action(
    goal_id: str,
    action_id: str,
    request: ActionReviewRequest,
    repository: GoalRepository = Depends(get_repository),
) -> AdministrativeGoal:
    """Approve or reject a proposed action. Nothing is ever sent automatically -
    this only records the human decision (and, on approval, an optional edited
    draft) against the stored goal."""
    goal = get_goal_or_404(goal_id, repository)
    try:
        updated_goal = review_action_proposal(
            goal,
            action_id,
            request.decision,
            edited_content=request.edited_content,
        )
    except ValueError as error:
        message = str(error)
        not_found = "was not found" in message
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND if not_found else status.HTTP_400_BAD_REQUEST,
            detail=message,
        ) from error
    return repository.save(updated_goal)
