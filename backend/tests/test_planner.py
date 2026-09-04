from datetime import datetime, timezone

from app.agents.planner import (
    build_dependency_graph,
    detect_cycles,
    generate_planning_risks,
    plan_goal,
    recommend_next_action,
    topological_order,
)
from app.models import (
    ActionProposal,
    ActionType,
    AdministrativeGoal,
    AdministrativeTask,
    RiskSeverity,
    TaskDependency,
    TaskStatus,
)
from app.models.enums import Priority


def make_task(
    task_id: str,
    title: str | None = None,
    dependencies: list[str] | None = None,
    status: TaskStatus = TaskStatus.NOT_STARTED,
    priority: Priority = Priority.MEDIUM,
) -> AdministrativeTask:
    return AdministrativeTask(
        id=task_id,
        title=title or task_id,
        description=f"Description for {task_id}",
        dependencies=[
            TaskDependency(prerequisite_task_id=dependency, reason="required")
            for dependency in (dependencies or [])
        ],
        status=status,
        priority=priority,
    )


def test_linear_chain_has_dependency_order() -> None:
    ordered, unorderable = topological_order(
        [make_task("C", dependencies=["B"]), make_task("B", dependencies=["A"]), make_task("A")]
    )

    assert ordered == ["A", "B", "C"]
    assert unorderable == []


def test_two_task_cycle_is_detected_and_excluded() -> None:
    tasks = [make_task("A", dependencies=["B"]), make_task("B", dependencies=["A"])]

    cycles = detect_cycles(build_dependency_graph(tasks))
    ordered, unorderable = topological_order(tasks)

    assert cycles == [["A", "B", "A"]]
    assert ordered == []
    assert set(unorderable) == {"A", "B"}


def test_longer_cycle_is_detected() -> None:
    tasks = [
        make_task("A", dependencies=["B"]),
        make_task("B", dependencies=["C"]),
        make_task("C", dependencies=["A"]),
    ]

    assert detect_cycles(build_dependency_graph(tasks)) == [["A", "B", "C", "A"]]


def test_clean_chain_is_ordered_alongside_cycle() -> None:
    tasks = [
        make_task("A", dependencies=["B"]),
        make_task("B", dependencies=["A"]),
        make_task("Y", dependencies=["X"]),
        make_task("X"),
    ]

    ordered, unorderable = topological_order(tasks)

    assert ordered == ["X", "Y"]
    assert set(unorderable) == {"A", "B"}


def test_cycle_generates_one_critical_risk() -> None:
    tasks = [make_task("A", dependencies=["B"]), make_task("B", dependencies=["A"])]

    risks = generate_planning_risks(tasks, build_dependency_graph(tasks))

    assert len(risks) == 1
    assert risks[0].severity is RiskSeverity.CRITICAL
    assert set(risks[0].related_task_ids) == {"A", "B"}


def test_dangling_dependency_generates_medium_risk_without_blocking_order() -> None:
    task = make_task("A", dependencies=["missing-task"])

    ordered, unorderable = topological_order([task])
    risks = generate_planning_risks([task], build_dependency_graph([task]))

    assert ordered == ["A"]
    assert unorderable == []
    assert len(risks) == 1
    assert risks[0].severity is RiskSeverity.MEDIUM
    assert risks[0].related_task_ids == ["A"]


def test_priority_breaks_ties_between_eligible_tasks() -> None:
    tasks = [
        make_task("low", priority=Priority.LOW),
        make_task("urgent", priority=Priority.URGENT),
    ]

    ordered, _ = topological_order(tasks)

    assert ordered == ["urgent", "low"]


def test_recommend_next_action_skips_incomplete_prerequisite() -> None:
    dependent = make_task("dependent", dependencies=["prerequisite"])
    prerequisite = make_task("prerequisite", status=TaskStatus.IN_PROGRESS)
    ready = make_task("ready")

    result = recommend_next_action([dependent, prerequisite, ready], ["dependent", "ready"])

    assert result is ready


def test_recommend_next_action_returns_none_when_no_action_is_available() -> None:
    tasks = [
        make_task("complete", status=TaskStatus.COMPLETED),
        make_task("blocked", status=TaskStatus.BLOCKED),
    ]

    assert recommend_next_action(tasks, ["complete", "blocked"]) is None


def test_plan_goal_adds_risks_and_next_action_without_mutating_input() -> None:
    cycle_a = make_task("cycle-a", dependencies=["cycle-b"])
    cycle_b = make_task("cycle-b", dependencies=["cycle-a"])
    ready = make_task("ready", title="Send reminder")
    goal = AdministrativeGoal(
        title="Resolve case",
        description="Resolve the administrative case.",
        final_deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
        tasks=[cycle_a, cycle_b, ready],
        proposed_actions=[
            ActionProposal(
                related_task_id=ready.id,
                action_type=ActionType.REMINDER,
                description="Send reminder",
            )
        ],
    )

    planned = plan_goal(goal)

    assert planned is not goal
    assert len(planned.risks) == 1
    assert planned.risks[0].severity is RiskSeverity.CRITICAL
    assert planned.next_action_summary == "Next recommended action: Send reminder."
    assert goal.risks == []
    assert goal.next_action_summary is None


def test_plan_goal_does_not_duplicate_unresolved_cycle_risk() -> None:
    goal = AdministrativeGoal(
        title="Resolve cycle",
        description="Resolve a circular plan.",
        tasks=[make_task("A", dependencies=["B"]), make_task("B", dependencies=["A"])],
    )

    planned_once = plan_goal(goal)
    planned_twice = plan_goal(planned_once)

    assert len(planned_once.risks) == 1
    assert len(planned_twice.risks) == 1
    assert planned_twice.risks[0].related_task_ids == ["A", "B"]