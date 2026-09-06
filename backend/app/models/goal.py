from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from .action import ActionProposal
from .document import DocumentSource
from .enums import GoalStatus
from .risk import Risk
from .task import AdministrativeTask


class AdministrativeGoal(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    description: str
    final_deadline: datetime | None = None
    status: GoalStatus = GoalStatus.ACTIVE
    documents: list[DocumentSource] = Field(default_factory=list)
    tasks: list[AdministrativeTask] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    proposed_actions: list[ActionProposal] = Field(default_factory=list)
    next_action_summary: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))