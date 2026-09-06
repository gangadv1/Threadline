from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from .enums import Priority, TaskStatus


class TaskDependency(BaseModel):
    prerequisite_task_id: str
    reason: str


class AdministrativeTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    description: str
    status: TaskStatus = TaskStatus.NOT_STARTED
    priority: Priority = Priority.MEDIUM
    deadline: datetime | None = None
    estimated_processing_time_days: float | None = None
    dependencies: list[TaskDependency] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    responsible_party: str | None = None
    consequence_if_missed: str | None = None
    confidence: float = 1.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("confidence must be between 0 and 1")
        return value

    @field_validator("estimated_processing_time_days")
    @classmethod
    def validate_processing_time(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("estimated_processing_time_days must not be negative")
        return value

    # NOTE: only rejects direct self-dependency (A depends on A). Multi-task cycles (A -> B -> A or longer) are NOT validated here by design — cycle detection across the full task graph belongs in the dependency-ordering/planning logic, where a detected cycle should be surfaced as a Risk, not silently rejected as invalid data. See project lead for the planning-layer implementation.
    @model_validator(mode="after")
    def reject_self_dependency(self) -> "AdministrativeTask":
        if any(dependency.prerequisite_task_id == self.id for dependency in self.dependencies):
            raise ValueError("a task cannot depend on itself")
        return self