import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.agents import (
    AgentPhase,
    AgentCycleResult,
    AgentStepRecord,
    run_agent_cycle,
    run_disruption_cycle,
)
from app.models import (
    ActionProposal,
    ActionType,
    AdministrativeGoal,
    AdministrativeTask,
    ApprovalStatus,
    TaskDependency,
    TaskStatus,
)


AS_OF = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)


def task(
    task_id: str,
    dependencies: list[str] | None = None,
    status: TaskStatus = TaskStatus.NOT_STARTED,
    days: float = 1,
    deadline: datetime | None = None,
) -> AdministrativeTask:
    return AdministrativeTask(
        id=task_id,
        title=f"Task {task_id}",
        description=f"Description for {task_id}",
        dependencies=[
            TaskDependency(prerequisite_task_id=item, reason="required")
            for item in (dependencies or [])
        ],
        status=status,
        estimated_processing_time_days=days,
        deadline=deadline,
    )


def goal(tasks: list[AdministrativeTask]) -> AdministrativeGoal:
    return AdministrativeGoal(
        id="goal-orchestrator",
        title="Orchestrator test goal",
        description="Test the complete agent cycle.",
        final_deadline=AS_OF + timedelta(days=10),
        tasks=tasks,
    )


def test_normal_cycle_returns_plan_feasibility_and_actions() -> None:
    source = goal([task("A"), task("B", ["A"])])

    result = run_agent_cycle(source, AS_OF)

    assert result.ordered_task_ids == ["A", "B"]
    assert result.recommended_next_task_id == "A"
    assert result.feasibility_report.goal_id == source.id
    assert result.newly_generated_action_ids
    assert result.updated_goal.proposed_actions
    assert [step.phase for step in result.step_records] == [
        AgentPhase.PLAN,
        AgentPhase.ANALYSE,
        AgentPhase.ACT,
    ]


def test_normal_cycle_does_not_mutate_goal_or_add_adapt() -> None:
    source = goal([task("A")])

    result = run_agent_cycle(source, AS_OF)

    assert source.proposed_actions == []
    assert source.next_action_summary is None
    assert all(step.phase is not AgentPhase.ADAPT for step in result.step_records)


def test_repeated_cycle_suppresses_duplicate_actions() -> None:
    source = goal([task("A")])

    first = run_agent_cycle(source, AS_OF)
    second = run_agent_cycle(first.updated_goal, AS_OF)

    assert first.newly_generated_action_ids
    assert second.newly_generated_action_ids == []
    assert len(second.updated_goal.proposed_actions) == len(first.updated_goal.proposed_actions)


def test_max_proposals_and_negative_limit() -> None:
    source = goal([task("A"), task("B"), task("C")])

    assert len(run_agent_cycle(source, AS_OF, max_proposals=1).newly_generated_action_ids) == 1
    with pytest.raises(ValueError, match="negative"):
        run_agent_cycle(source, AS_OF, max_proposals=-1)


def test_disruption_replans_and_blocks_downstream_tasks() -> None:
    source = goal([
        task("A"),
        task("B", ["A"]),
        task("C", ["B"]),
        task("done", status=TaskStatus.COMPLETED),
    ])

    result = run_disruption_cycle(source, "A", TaskStatus.REJECTED, AS_OF, reason="Requirement was declined.")

    statuses = {item.id: item.status for item in result.updated_goal.tasks}
    assert result.replanning_occurred is True
    assert statuses["A"] is TaskStatus.REJECTED
    assert statuses["B"] is TaskStatus.BLOCKED
    assert statuses["C"] is TaskStatus.BLOCKED
    assert statuses["done"] is TaskStatus.COMPLETED
    assert "Requirement was declined." in (result.disruption_summary or "")
    assert result.step_records[0].phase is AgentPhase.ADAPT
    assert set(result.step_records[0].related_task_ids) == {"A", "B", "C"}


def test_deadline_disruption_recalculates_without_blocking() -> None:
    source = goal([task("A"), task("B", ["A"])])
    new_deadline = AS_OF + timedelta(days=1)

    result = run_disruption_cycle(source, "A", TaskStatus.NOT_STARTED, AS_OF, new_deadline=new_deadline)

    statuses = {item.id: item.status for item in result.updated_goal.tasks}
    assert statuses["A"] is TaskStatus.NOT_STARTED
    assert statuses["B"] is TaskStatus.NOT_STARTED
    assert result.updated_goal.tasks[0].deadline == new_deadline
    assert "New deadline" in (result.disruption_summary or "")


def test_disruption_step_records_use_supplied_timestamp_and_no_execution_claims() -> None:
    result = run_disruption_cycle(goal([task("A")]), "A", TaskStatus.BLOCKED, AS_OF)

    assert all(step.timestamp == AS_OF for step in result.step_records)
    assert all("executed" not in step.explanation.lower() for step in result.step_records)
    assert all("sent" not in step.explanation.lower() for step in result.step_records)


def test_unknown_task_and_naive_datetime_raise() -> None:
    source = goal([task("A")])

    with pytest.raises(ValueError, match="not found"):
        run_disruption_cycle(source, "missing", TaskStatus.BLOCKED, AS_OF)
    with pytest.raises(ValueError, match="timezone-aware"):
        run_agent_cycle(source, AS_OF.replace(tzinfo=None))


def test_results_serialize_and_preserve_existing_reviewed_actions() -> None:
    source = goal([task("A")])
    approved = ActionProposal(
        related_task_id="A",
        action_type=ActionType.REMINDER,
        description="Existing approved reminder",
        approval_status=ApprovalStatus.APPROVED,
    )
    rejected = ActionProposal(
        related_task_id="B",
        action_type=ActionType.REQUEST_INFO,
        description="Existing rejected request",
        approval_status=ApprovalStatus.REJECTED,
    )
    source.proposed_actions = [approved, rejected]

    result = run_agent_cycle(source, AS_OF)
    serialized = result.model_dump(mode="json")

    assert serialized["cycle_timestamp"] == AS_OF.isoformat().replace("+00:00", "Z")
    assert {item["approval_status"] for item in serialized["updated_goal"]["proposed_actions"]} >= {
        "approved",
        "rejected",
    }
    assert AgentCycleResult.model_validate(serialized).updated_goal.id == source.id


def test_exchange_sample_runs_normal_and_transcript_rejection_cycles() -> None:
    sample_path = Path(__file__).parents[2] / "sample_data" / "exchange_application_demo.json"
    sample_goal = AdministrativeGoal.model_validate(json.loads(sample_path.read_text()))

    normal = run_agent_cycle(sample_goal, AS_OF)
    disrupted = run_disruption_cycle(
        sample_goal,
        "task-request-transcript",
        TaskStatus.REJECTED,
        AS_OF,
        reason="An unpaid fee prevented transcript release.",
    )

    assert normal.ordered_task_ids
    disrupted_statuses = {item.id: item.status for item in disrupted.updated_goal.tasks}
    assert disrupted_statuses["task-request-transcript"] is TaskStatus.REJECTED
    assert disrupted_statuses["task-upload-supporting-documents"] is TaskStatus.BLOCKED
    assert disrupted.replanning_occurred is True
    assert disrupted.feasibility_report is not None
    assert disrupted.newly_generated_action_ids
    assert "unpaid fee" in (disrupted.disruption_summary or "")


def test_existing_public_agent_imports_continue_working() -> None:
    from app.agents import analyze_goal_feasibility, generate_action_proposals
    from app.agents.planner import plan_goal

    assert callable(analyze_goal_feasibility)
    assert callable(generate_action_proposals)
    assert callable(plan_goal)