from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.agents import AgentCycleResult, run_agent_cycle, run_disruption_cycle
from app.api.dependencies import get_goal_or_404, get_repository
from app.api.schemas import DisruptionRequest, RunCycleRequest
from app.database import GoalRepository

router = APIRouter(prefix="/goals", tags=["cycles"])


@router.post("/{goal_id}/cycle", response_model=AgentCycleResult)
def run_cycle(
    goal_id: str,
    request: RunCycleRequest,
    repository: GoalRepository = Depends(get_repository),
) -> AgentCycleResult:
    """Run PLAN, ANALYSE and ACT for a goal and persist the result."""
    goal = get_goal_or_404(goal_id, repository)
    try:
        result = run_agent_cycle(goal, request.as_of, max_proposals=request.max_proposals)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    repository.save(result.updated_goal)
    return result


@router.post("/{goal_id}/disruption", response_model=AgentCycleResult)
def run_disruption(
    goal_id: str,
    request: DisruptionRequest,
    repository: GoalRepository = Depends(get_repository),
) -> AgentCycleResult:
    """Report a disruption (rejection, delay, blocker) and re-run planning.

    This runs the ADAPT phase (replanning + downstream blocking) followed by
    ANALYSE and ACT, and persists the resulting goal state.
    """
    goal = get_goal_or_404(goal_id, repository)
    try:
        result = run_disruption_cycle(
            goal,
            request.task_id,
            request.new_status,
            request.as_of,
            new_deadline=request.new_deadline,
            reason=request.reason,
            max_proposals=request.max_proposals,
        )
    except ValueError as error:
        message = str(error)
        not_found = "not found" in message.lower()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND if not_found else status.HTTP_400_BAD_REQUEST,
            detail=message,
        ) from error
    repository.save(result.updated_goal)
    return result
