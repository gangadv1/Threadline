from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from .enums import RiskSeverity


class Risk(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    related_task_ids: list[str] = Field(default_factory=list)
    severity: RiskSeverity
    explanation: str
    recommended_response: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved: bool = False