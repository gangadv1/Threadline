"""API-only request/response shapes.

These are deliberately kept separate from `app.models`: the domain models
(`AdministrativeGoal`, `AdministrativeTask`, ...) describe the workflow data
itself, while the models here describe the *wire format* of specific
endpoints (e.g. "what fields can you PATCH on a task"). Keeping them apart
means Member 1's domain models can evolve without every endpoint's request
body changing shape.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models import ApprovalStatus, GoalStatus, TaskStatus


class HealthResponse(BaseModel):
    status: str = "ok"


class GoalSummary(BaseModel):
    """Lightweight representation used for the goals list endpoint."""

    id: str
    title: str
    status: GoalStatus
    final_deadline: datetime | None = None
    next_action_summary: str | None = None
    task_count: int
    open_risk_count: int
    updated_at: datetime


class GoalUpdateRequest(BaseModel):
    """Direct update to a goal's own fields (not its tasks).

    Used for corrections like an earlier final deadline. This does not
    re-run planning by itself - call POST /goals/{id}/cycle afterwards to
    refresh feasibility, risks, and proposed actions against the new value.
    """

    title: str | None = None
    description: str | None = None
    final_deadline: datetime | None = None
    status: GoalStatus | None = None

    def is_empty(self) -> bool:
        return all(
            value is None
            for value in (self.title, self.description, self.final_deadline, self.status)
        )


class TaskStatusUpdateRequest(BaseModel):
    """Direct, non-replanning update to a single task's status/deadline.

    Use this for correcting or entering data before a plan has been run.
    To propagate the effects of a disruption to downstream tasks, use the
    /disruption endpoint instead, which re-runs planning and feasibility.
    """

    status: TaskStatus | None = None
    deadline: datetime | None = None

    def is_empty(self) -> bool:
        return self.status is None and self.deadline is None


class DisruptionRequest(BaseModel):
    task_id: str
    new_status: TaskStatus
    as_of: datetime
    new_deadline: datetime | None = None
    reason: str | None = None
    max_proposals: int = Field(default=5, ge=0)


class RunCycleRequest(BaseModel):
    as_of: datetime
    max_proposals: int = Field(default=5, ge=0)


class ActionReviewRequest(BaseModel):
    decision: ApprovalStatus
    edited_content: str | None = None


class ErrorResponse(BaseModel):
    detail: str
