from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models import (
    ActionProposal,
    ActionType,
    AdministrativeGoal,
    AdministrativeTask,
    ApprovalStatus,
    DocumentSource,
    DocumentType,
    Risk,
    RiskSeverity,
    TaskDependency,
)
from app.models.enums import Priority, TaskStatus


def test_administrative_task_defaults() -> None:
    task = AdministrativeTask(title="Review notice", description="Review the notice")

    assert task.status is TaskStatus.NOT_STARTED
    assert task.priority is Priority.MEDIUM
    assert task.confidence == 1.0
    assert task.dependencies == []
    assert task.source_ids == []
    assert task.created_at.tzinfo == timezone.utc
    assert task.updated_at.tzinfo == timezone.utc


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_must_be_between_zero_and_one(confidence: float) -> None:
    with pytest.raises(ValidationError):
        AdministrativeTask(
            title="Review notice",
            description="Review the notice",
            confidence=confidence,
        )


def test_estimated_processing_time_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        AdministrativeTask(
            title="Review notice",
            description="Review the notice",
            estimated_processing_time_days=-1,
        )


def test_task_cannot_depend_on_itself() -> None:
    task_id = "task-1"

    with pytest.raises(ValidationError):
        AdministrativeTask(
            id=task_id,
            title="Review notice",
            description="Review the notice",
            dependencies=[TaskDependency(prerequisite_task_id=task_id, reason="self")],
        )


def test_task_can_depend_on_a_different_task() -> None:
    task = AdministrativeTask(
        id="task-2",
        title="Complete follow-up",
        description="Complete the follow-up",
        dependencies=[
            TaskDependency(prerequisite_task_id="task-1", reason="Prior review required")
        ],
    )

    assert task.dependencies[0].prerequisite_task_id == "task-1"


def test_task_lists_are_not_shared_between_instances() -> None:
    first = AdministrativeTask(title="First", description="First task")
    second = AdministrativeTask(title="Second", description="Second task")

    assert first.dependencies is not second.dependencies
    assert first.source_ids is not second.source_ids


def test_full_goal_serializes_to_json() -> None:
    task = AdministrativeTask(title="Review notice", description="Review the notice")
    goal = AdministrativeGoal(
        title="Resolve administrative notice",
        description="Complete all required follow-up work.",
        final_deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
        documents=[
            DocumentSource(
                filename="notice.pdf",
                document_type=DocumentType.PDF,
                source_text="Notice content",
            )
        ],
        tasks=[task],
        risks=[
            Risk(
                related_task_ids=[task.id],
                severity=RiskSeverity.MEDIUM,
                explanation="The deadline is approaching.",
                recommended_response="Review the notice promptly.",
            )
        ],
        proposed_actions=[
            ActionProposal(
                related_task_id=task.id,
                action_type=ActionType.REMINDER,
                description="Send a reminder.",
            )
        ],
    )

    serialized = goal.model_dump(mode="json")

    assert serialized["status"] == "active"
    assert serialized["documents"][0]["document_type"] == "pdf"
    assert isinstance(serialized["created_at"], str)
    assert serialized["proposed_actions"][0]["action_type"] == "reminder"


def test_action_proposal_defaults_to_pending_approval() -> None:
    action = ActionProposal(
        related_task_id="task-1",
        action_type=ActionType.REQUEST_INFO,
        description="Request more information.",
    )

    assert action.approval_status is ApprovalStatus.PENDING