from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from .enums import ActionType, ApprovalStatus


class ActionProposal(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    related_task_id: str
    action_type: ActionType
    description: str
    generated_content: str | None = None
    requires_approval: bool = True
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))