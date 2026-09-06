import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.agents.replanner import (
    apply_disruption,
    find_downstream_tasks,
    replan_after_disruption,
    summarize_changes,
)
from app.models import AdministrativeGoal, AdministrativeTask, TaskDependency, TaskStatus


def make_task(
    task_id: str,
    dependencies: list[str] | None = None,
    status: TaskStatus = TaskStatus.NOT_STARTED,
) -> AdministrativeTask:
    return AdministrativeTask(
        id=task_id,
        title=f"Task {task_id}",
        description=f"Description for {task_id}",
        dependencies=[
            TaskDependency(prerequisite_task_id=dependency, reason="required")
            for dependency in (dependencies or [])
        ],
        status=status,
    )


def make_goal(tasks: list[AdministrativeTask]) -> AdministrativeGoal:
    return AdministrativeGoal(
        title="Test goal",
        description="Test goal description",
        final_deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
        tasks=tasks,
    )


def test_find_downstream_tasks_returns_transitive_dependents() -> None:
    tasks = [make_task("A"), make_task("B", ["A"]), make_task("C", ["B"])]

    assert find_downstream_tasks("A", tasks) == ["B", "C"]


def test_find_downstream_tasks_returns_empty_for_leaf_task() -> None:
    assert find_downstream_tasks("A", [make_task("A"), make_task("B")]) == []


def test_rejected_task_blocks_all_downstream_tasks() -> None:
    goal = make_goal([make_task("A"), make_task("B", ["A"]), make_task("C", ["B"])])

    updated, downstream = apply_disruption(goal, "A", TaskStatus.REJECTED)

    assert downstream == ["B", "C"]
    assert [task.status for task in updated.tasks] == [
        TaskStatus.REJECTED,
        TaskStatus.BLOCKED,
        TaskStatus.BLOCKED,
    ]


def test_completed_downstream_task_is_not_downgraded() -> None:
    goal = make_goal(
        [
            make_task("A"),
            make_task("B", ["A"], status=TaskStatus.COMPLETED),
            make_task("C", ["B"]),
        ]
    )

    updated, _ = apply_disruption(goal, "A", TaskStatus.BLOCKED)

    assert updated.tasks[1].status is TaskStatus.COMPLETED
    assert updated.tasks[2].status is TaskStatus.BLOCKED


def test_apply_disruption_rejects_unknown_task() -> None:
    with pytest.raises(ValueError, match="was not found"):
        apply_disruption(make_goal([make_task("A")]), "missing", TaskStatus.BLOCKED)


def test_apply_disruption_does_not_mutate_original_goal() -> None:
    goal = make_goal([make_task("A"), make_task("B", ["A"])])

    updated, _ = apply_disruption(goal, "A", TaskStatus.REJECTED)

    assert goal.tasks[0].status is TaskStatus.NOT_STARTED
    assert goal.tasks[1].status is TaskStatus.NOT_STARTED
    assert updated.tasks[0].status is TaskStatus.REJECTED


def test_summarize_changes_mentions_titles_and_downstream_effects() -> None:
    original = make_goal([make_task("A"), make_task("B", ["A"]), make_task("C", ["B"])])
    updated, downstream = apply_disruption(original, "A", TaskStatus.REJECTED)

    summary = summarize_changes(original, updated, "A", downstream)

    assert "Task A" in summary
    assert "Task B" in summary
    assert "Task C" in summary
    assert "rejected" in summary


def test_summarize_changes_mentions_no_affected_tasks() -> None:
    original = make_goal([make_task("A")])
    updated, downstream = apply_disruption(original, "A", TaskStatus.BLOCKED)

    summary = summarize_changes(original, updated, "A", downstream)

    assert "No other tasks are affected." in summary


def test_replan_after_disruption_updates_goal_and_summary() -> None:
    eligibility = make_task("eligibility", status=TaskStatus.COMPLETED)
    transcript = make_task("transcript", ["eligibility"])
    reference = make_task("reference", ["eligibility"])
    upload = make_task("upload", ["transcript", "reference"])
    submit = make_task("submit", ["upload"])
    goal = make_goal([eligibility, transcript, reference, upload, submit])

    final_goal, summary = replan_after_disruption(
        goal, "transcript", new_status=TaskStatus.REJECTED
    )

    statuses = {task.id: task.status for task in final_goal.tasks}
    assert statuses["transcript"] is TaskStatus.REJECTED
    assert statuses["upload"] is TaskStatus.BLOCKED
    assert statuses["submit"] is TaskStatus.BLOCKED
    assert final_goal.next_action_summary is not None
    assert "reference" in final_goal.next_action_summary.lower()
    assert "rejected" in summary


def test_sample_exchange_goal_is_valid() -> None:
    sample_path = Path(__file__).parents[2] / "sample_data" / "exchange_application_demo.json"
    payload = json.loads(sample_path.read_text())

    goal = AdministrativeGoal.model_validate(payload)

    assert goal.title == "Submit exchange application"
    assert len(goal.tasks) == 6