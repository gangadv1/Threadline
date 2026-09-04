from datetime import datetime, timedelta, timezone

import pytest

from app.agents.actions import (
    add_action_proposals,
    generate_action_proposals,
    review_action_proposal,
)
from app.agents.feasibility import FeasibilityStatus, analyze_goal_feasibility
from app.models import (
    ActionProposal,
    ActionType,
    AdministrativeGoal,
    AdministrativeTask,
    ApprovalStatus,
    RiskSeverity,
    TaskDependency,
    TaskStatus,
)


AS_OF = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)


def make_task(
    task_id: str,
    status: TaskStatus = TaskStatus.NOT_STARTED,
    days: float | None = 1,
    deadline: datetime | None = None,
    dependencies: list[str] | None = None,
    confidence: float = 1.0,
    responsible_party: str | None = None,
    source_ids: list[str] | None = None,
) -> AdministrativeTask:
    return AdministrativeTask(
        id=task_id,
        title=f"Task {task_id}",
        description=f"Description for {task_id}",
        status=status,
        estimated_processing_time_days=days,
        deadline=deadline,
        dependencies=[
            TaskDependency(prerequisite_task_id=item, reason="required")
            for item in (dependencies or [])
        ],
        confidence=confidence,
        responsible_party=responsible_party,
        source_ids=source_ids or [],
    )


def make_goal(tasks: list[AdministrativeTask], deadline: datetime | None = None) -> AdministrativeGoal:
    return AdministrativeGoal(
        id="goal-actions",
        title="Action test goal",
        description="Test action proposals",
        final_deadline=deadline,
        tasks=tasks,
    )


def proposals_for(goal: AdministrativeGoal, report=None, limit: int = 5) -> list[ActionProposal]:
    return generate_action_proposals(goal, report, AS_OF, max_proposals=limit)


def test_normal_actionable_task_generates_reminder() -> None:
    proposals = proposals_for(make_goal([make_task("A")]))

    assert len(proposals) == 1
    assert proposals[0].action_type is ActionType.REMINDER
    assert "Task A" in proposals[0].description
    assert proposals[0].requires_approval is True


def test_completed_task_generates_no_proposal() -> None:
    assert proposals_for(make_goal([make_task("A", status=TaskStatus.COMPLETED)])) == []


def test_blocked_prerequisite_generates_blocker_resolution_proposal() -> None:
    goal = make_goal([make_task("A", status=TaskStatus.BLOCKED, responsible_party="Records Office")])

    proposals = proposals_for(goal)

    assert proposals[0].action_type is ActionType.REQUEST_INFO
    assert "Records Office" in proposals[0].description
    assert "sent" not in (proposals[0].generated_content or "").lower()


def test_infeasible_deadline_generates_escalation() -> None:
    goal = make_goal([make_task("A", days=5)], deadline=AS_OF + timedelta(days=2))
    report = analyze_goal_feasibility(goal, AS_OF)

    proposals = proposals_for(goal, report)

    assert report.overall_status is FeasibilityStatus.INFEASIBLE
    assert any(proposal.action_type is ActionType.ESCALATION for proposal in proposals)
    assert "extension" in (proposals[0].generated_content or "").lower()


def test_overdue_task_does_not_receive_normal_reminder() -> None:
    goal = make_goal(
        [make_task("A", deadline=AS_OF - timedelta(days=1))],
        deadline=AS_OF + timedelta(days=5),
    )
    report = analyze_goal_feasibility(goal, AS_OF)

    proposals = proposals_for(goal, report)

    assert proposals[0].action_type is ActionType.ESCALATION
    assert not any(proposal.action_type is ActionType.REMINDER for proposal in proposals)


def test_low_confidence_task_generates_verification() -> None:
    goal = make_goal(
        [make_task("A", confidence=0.5, source_ids=["doc-1"])],
        deadline=AS_OF + timedelta(days=5),
    )
    report = analyze_goal_feasibility(goal, AS_OF)

    proposals = proposals_for(goal, report)

    assert proposals[0].action_type is ActionType.REQUEST_INFO
    assert "doc-1" in proposals[0].description


def test_zero_slack_is_prioritised_above_normal_action() -> None:
    urgent = make_task("urgent", days=2)
    normal = make_task("normal", days=1)
    goal = make_goal([urgent, normal], deadline=AS_OF + timedelta(days=2))
    report = analyze_goal_feasibility(goal, AS_OF)

    proposals = proposals_for(goal, report)

    assert proposals[0].related_task_id == "urgent"


def test_blocked_critical_path_is_prioritised_first() -> None:
    blocked = make_task("blocked", status=TaskStatus.BLOCKED)
    normal = make_task("normal")
    goal = make_goal([blocked, normal], deadline=AS_OF + timedelta(days=5))
    report = analyze_goal_feasibility(goal, AS_OF)

    proposals = proposals_for(goal, report)

    assert proposals[0].related_task_id == "blocked"
    assert proposals[0].action_type is ActionType.REQUEST_INFO


def test_proposal_limits_are_respected() -> None:
    goal = make_goal(
        [make_task("A", confidence=0.5), make_task("B", confidence=0.5)],
        deadline=AS_OF + timedelta(days=5),
    )
    report = analyze_goal_feasibility(goal, AS_OF)

    assert len(proposals_for(goal, report, limit=1)) == 1
    assert proposals_for(goal, report, limit=0) == []
    with pytest.raises(ValueError, match="negative"):
        proposals_for(goal, report, limit=-1)


def test_existing_equivalent_proposal_is_not_duplicated() -> None:
    goal = make_goal([make_task("A")])
    existing = ActionProposal(
        related_task_id="A",
        action_type=ActionType.REMINDER,
        description="Existing next action reminder.",
    )
    goal.proposed_actions = [existing]

    assert proposals_for(goal) == []


def test_approval_updates_only_selected_proposal() -> None:
    first = ActionProposal(related_task_id="A", action_type=ActionType.REMINDER, description="First")
    second = ActionProposal(related_task_id="B", action_type=ActionType.REMINDER, description="Second")
    goal = make_goal([])
    goal.proposed_actions = [first, second]

    reviewed = review_action_proposal(goal, first.id, "approved")

    assert reviewed.proposed_actions[0].approval_status is ApprovalStatus.APPROVED
    assert reviewed.proposed_actions[1].approval_status is ApprovalStatus.PENDING
    assert goal.proposed_actions[0].approval_status is ApprovalStatus.PENDING


def test_approval_with_edited_content_preserves_edit() -> None:
    proposal = ActionProposal(related_task_id="A", action_type=ActionType.DRAFT_EMAIL, description="Draft")
    goal = make_goal([])
    goal.proposed_actions = [proposal]

    reviewed = review_action_proposal(goal, proposal.id, ApprovalStatus.APPROVED, "Edited draft")

    assert reviewed.proposed_actions[0].generated_content == "Edited draft"


def test_rejection_preserves_original_content() -> None:
    proposal = ActionProposal(
        related_task_id="A",
        action_type=ActionType.DRAFT_EMAIL,
        description="Draft",
        generated_content="Original draft",
    )
    goal = make_goal([])
    goal.proposed_actions = [proposal]

    reviewed = review_action_proposal(goal, proposal.id, "rejected", "Ignored edit")

    assert reviewed.proposed_actions[0].approval_status is ApprovalStatus.REJECTED
    assert reviewed.proposed_actions[0].generated_content == "Original draft"


def test_review_errors_are_clear_and_reviewed_actions_cannot_reverse() -> None:
    proposal = ActionProposal(related_task_id="A", action_type=ActionType.REMINDER, description="Reminder")
    goal = make_goal([])
    goal.proposed_actions = [proposal]

    with pytest.raises(ValueError, match="not found"):
        review_action_proposal(goal, "missing", "approved")
    with pytest.raises(ValueError, match="approved or rejected"):
        review_action_proposal(goal, proposal.id, "sent")

    approved = review_action_proposal(goal, proposal.id, "approved")
    with pytest.raises(ValueError, match="already reviewed"):
        review_action_proposal(approved, proposal.id, "rejected")


def test_add_and_generation_do_not_mutate_goal() -> None:
    goal = make_goal([make_task("A")])
    proposals = proposals_for(goal)
    updated = add_action_proposals(goal, proposals)

    assert goal.proposed_actions == []
    assert len(updated.proposed_actions) == 1


def test_proposals_serialize_and_order_is_repeatable() -> None:
    goal = make_goal([make_task("B"), make_task("A")])

    first = proposals_for(goal)
    second = proposals_for(goal)

    assert [item.related_task_id for item in first] == [item.related_task_id for item in second]
    assert first[0].model_dump(mode="json")["approval_status"] == "pending"
    assert all("email@" not in (item.generated_content or "") for item in first)
    assert all("submitted" not in item.description.lower() for item in first)