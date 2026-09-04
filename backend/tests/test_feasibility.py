import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agents.feasibility import FeasibilityStatus, analyze_goal_feasibility
from app.models import AdministrativeGoal, AdministrativeTask, TaskDependency, TaskStatus


AS_OF = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)


def task(
    task_id: str,
    days: float | None,
    dependencies: list[str] | None = None,
    deadline: datetime | None = None,
    status: TaskStatus = TaskStatus.NOT_STARTED,
    confidence: float = 1.0,
) -> AdministrativeTask:
    return AdministrativeTask(
        id=task_id,
        title=f"Task {task_id}",
        description=f"Description for {task_id}",
        estimated_processing_time_days=days,
        dependencies=[
            TaskDependency(prerequisite_task_id=item, reason="required")
            for item in (dependencies or [])
        ],
        deadline=deadline,
        status=status,
        confidence=confidence,
    )


def goal(tasks: list[AdministrativeTask], deadline: datetime | None) -> AdministrativeGoal:
    return AdministrativeGoal(
        id="goal-1",
        title="Test goal",
        description="Test feasibility",
        final_deadline=deadline,
        tasks=tasks,
    )


def test_dependency_chain_completes_before_deadline() -> None:
    report = analyze_goal_feasibility(
        goal([task("A", 2), task("B", 3, ["A"])], AS_OF + timedelta(days=10)), AS_OF
    )

    assert report.overall_status is FeasibilityStatus.ON_TRACK
    assert report.projected_goal_completion_date == AS_OF + timedelta(days=5)
    assert report.critical_path_task_ids == ["A", "B"]


def test_critical_path_contains_the_tasks_that_determine_completion() -> None:
    report = analyze_goal_feasibility(
        goal(
            [task("short", 1), task("long", 4), task("finish", 1, ["long"])],
            AS_OF + timedelta(days=10),
        ),
        AS_OF,
    )

    assert report.critical_path_task_ids == ["long", "finish"]


def test_dependency_chain_misses_deadline() -> None:
    report = analyze_goal_feasibility(
        goal([task("A", 4), task("B", 4, ["A"])], AS_OF + timedelta(days=5)), AS_OF
    )

    assert report.overall_status is FeasibilityStatus.INFEASIBLE
    assert any(issue.issue_type == "DEADLINE_MISS" for issue in report.detected_issues)


def test_independent_tasks_run_in_parallel() -> None:
    report = analyze_goal_feasibility(
        goal([task("A", 5), task("B", 5)], AS_OF + timedelta(days=6)), AS_OF
    )

    assert report.projected_goal_completion_date == AS_OF + timedelta(days=5)


def test_multiple_prerequisites_wait_for_latest() -> None:
    report = analyze_goal_feasibility(
        goal(
            [task("A", 2), task("B", 5), task("C", 1, ["A", "B"])],
            AS_OF + timedelta(days=10),
        ),
        AS_OF,
    )

    projection = next(item for item in report.task_projections if item.task_id == "C")
    assert projection.earliest_possible_start == AS_OF + timedelta(days=5)
    assert projection.projected_completion_date == AS_OF + timedelta(days=6)
    assert projection.dependency_ids_affecting_start == ["B"]


def test_completed_prerequisite_adds_no_processing_delay() -> None:
    report = analyze_goal_feasibility(
        goal(
            [
                task("A", 20, status=TaskStatus.COMPLETED),
                task("B", 2, ["A"]),
            ],
            AS_OF + timedelta(days=3),
        ),
        AS_OF,
    )

    projection = next(item for item in report.task_projections if item.task_id == "B")
    assert projection.earliest_possible_start == AS_OF
    assert projection.projected_completion_date == AS_OF + timedelta(days=2)


def test_incomplete_overdue_task_is_flagged() -> None:
    report = analyze_goal_feasibility(
        goal([task("A", 1, deadline=AS_OF - timedelta(days=1))], AS_OF + timedelta(days=5)), AS_OF
    )

    assert any(issue.issue_type == "OVERDUE_TASK" for issue in report.detected_issues)


def test_completed_task_is_not_overdue() -> None:
    report = analyze_goal_feasibility(
        goal(
            [task("A", 1, deadline=AS_OF - timedelta(days=1), status=TaskStatus.COMPLETED)],
            AS_OF + timedelta(days=5),
        ),
        AS_OF,
    )

    assert not any(issue.issue_type == "OVERDUE_TASK" for issue in report.detected_issues)
    assert report.overall_status is FeasibilityStatus.COMPLETED


def test_blocked_prerequisite_makes_plan_infeasible() -> None:
    report = analyze_goal_feasibility(
        goal(
            [task("A", 1, status=TaskStatus.BLOCKED), task("B", 1, ["A"])],
            AS_OF + timedelta(days=5),
        ),
        AS_OF,
    )

    assert report.overall_status is FeasibilityStatus.INFEASIBLE
    assert any(issue.issue_type == "BLOCKED_TASK" for issue in report.detected_issues)


def test_missing_processing_time_is_uncertain() -> None:
    report = analyze_goal_feasibility(
        goal([task("A", None)], AS_OF + timedelta(days=5)), AS_OF
    )

    assert report.overall_status is FeasibilityStatus.INSUFFICIENT_INFORMATION
    assert any(issue.issue_type == "MISSING_PROCESSING_TIME" for issue in report.detected_issues)


def test_low_confidence_is_at_risk() -> None:
    report = analyze_goal_feasibility(
        goal([task("A", 1, confidence=0.69)], AS_OF + timedelta(days=5)), AS_OF
    )

    assert report.overall_status is FeasibilityStatus.AT_RISK
    assert any(issue.issue_type == "LOW_CONFIDENCE" for issue in report.detected_issues)


def test_original_goal_is_not_mutated() -> None:
    source = goal([task("A", 2)], AS_OF + timedelta(days=5))
    original_deadline = source.final_deadline
    report = analyze_goal_feasibility(source, AS_OF)

    assert source.final_deadline == original_deadline
    assert source.tasks[0].status is TaskStatus.NOT_STARTED
    assert report.goal_id == source.id


def test_completed_goal_is_completed() -> None:
    report = analyze_goal_feasibility(
        goal([task("A", 2, status=TaskStatus.COMPLETED)], AS_OF + timedelta(days=5)), AS_OF
    )

    assert report.overall_status is FeasibilityStatus.COMPLETED


def test_exchange_sample_is_analyzable() -> None:
    path = Path(__file__).parents[2] / "sample_data" / "exchange_application_demo.json"
    sample_goal = AdministrativeGoal.model_validate(json.loads(path.read_text()))

    report = analyze_goal_feasibility(sample_goal, AS_OF)

    assert report.goal_id == sample_goal.id
    assert report.projected_goal_completion_date is not None
    assert report.critical_path_task_ids


def test_report_serializes_to_json() -> None:
    report = analyze_goal_feasibility(
        goal([task("A", 1)], AS_OF + timedelta(days=5)), AS_OF
    )

    serialized = report.model_dump(mode="json")

    assert serialized["analysis_timestamp"] == AS_OF.isoformat().replace("+00:00", "Z")
    assert serialized["overall_status"] == "on_track"
    assert isinstance(serialized["task_projections"][0]["projected_completion_date"], str)