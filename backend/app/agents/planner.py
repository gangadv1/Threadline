from datetime import datetime, timezone

from app.models import (
    AdministrativeGoal,
    AdministrativeTask,
    Priority,
    Risk,
    RiskSeverity,
    TaskStatus,
)


_PRIORITY_RANK = {
    Priority.URGENT: 0,
    Priority.HIGH: 1,
    Priority.MEDIUM: 2,
    Priority.LOW: 3,
}


def build_dependency_graph(tasks: list[AdministrativeTask]) -> dict[str, list[str]]:
    """Build a task-to-prerequisites graph, excluding dangling references."""
    task_ids = {task.id for task in tasks}
    return {
        task.id: [
            dependency.prerequisite_task_id
            for dependency in task.dependencies
            if dependency.prerequisite_task_id in task_ids
        ]
        for task in tasks
    }


def _canonical_cycle(cycle: list[str]) -> tuple[str, ...]:
    nodes = cycle[:-1]
    rotations = [tuple(nodes[index:] + nodes[:index]) for index in range(len(nodes))]
    return min(rotations)


def detect_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """Return each directed cycle once, with its first node repeated at the end."""
    state: dict[str, int] = {}
    stack: list[str] = []
    stack_positions: dict[str, int] = {}
    cycles: dict[tuple[str, ...], list[str]] = {}
    nodes = set(graph)
    for prerequisites in graph.values():
        nodes.update(prerequisites)

    def visit(node: str) -> None:
        state[node] = 1
        stack_positions[node] = len(stack)
        stack.append(node)

        for prerequisite in sorted(graph.get(node, [])):
            if state.get(prerequisite, 0) == 0:
                visit(prerequisite)
            elif state.get(prerequisite) == 1:
                cycle = stack[stack_positions[prerequisite] :] + [prerequisite]
                canonical = _canonical_cycle(cycle)
                cycles[canonical] = list(canonical) + [canonical[0]]

        stack.pop()
        stack_positions.pop(node, None)
        state[node] = 2

    for node in sorted(nodes):
        if state.get(node, 0) == 0:
            visit(node)

    return [cycles[key] for key in sorted(cycles)]


def _deadline_sort_key(task: AdministrativeTask) -> tuple[int, float]:
    if task.deadline is None:
        return (1, 0.0)
    deadline = task.deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return (0, deadline.timestamp())


def _task_sort_key(task: AdministrativeTask) -> tuple[int, tuple[int, float], str, str]:
    return (
        _PRIORITY_RANK[task.priority],
        _deadline_sort_key(task),
        task.title.casefold(),
        task.id,
    )


def topological_order(tasks: list[AdministrativeTask]) -> tuple[list[str], list[str]]:
    """Order tasks by prerequisites and deterministic priority tie-breaking."""
    graph = build_dependency_graph(tasks)
    task_by_id = {task.id: task for task in tasks}
    in_degree = {task_id: len(prerequisites) for task_id, prerequisites in graph.items()}
    dependents: dict[str, list[str]] = {task_id: [] for task_id in graph}
    for task_id, prerequisites in graph.items():
        for prerequisite in prerequisites:
            dependents[prerequisite].append(task_id)

    eligible = [task for task_id, task in task_by_id.items() if in_degree[task_id] == 0]
    eligible.sort(key=_task_sort_key)
    ordered: list[str] = []

    while eligible:
        eligible.sort(key=_task_sort_key)
        task = eligible.pop(0)
        ordered.append(task.id)
        for dependent_id in dependents[task.id]:
            in_degree[dependent_id] -= 1
            if in_degree[dependent_id] == 0:
                eligible.append(task_by_id[dependent_id])

    unorderable = [task.id for task in tasks if task.id not in ordered]
    return ordered, unorderable


def _task_label(task_by_id: dict[str, AdministrativeTask], task_id: str) -> str:
    task = task_by_id.get(task_id)
    return task.title if task is not None else task_id


def _dangling_dependencies(
    tasks: list[AdministrativeTask],
) -> list[tuple[AdministrativeTask, str]]:
    task_ids = {task.id for task in tasks}
    return [
        (task, dependency.prerequisite_task_id)
        for task in tasks
        for dependency in task.dependencies
        if dependency.prerequisite_task_id not in task_ids
    ]


def generate_planning_risks(
    tasks: list[AdministrativeTask], graph: dict[str, list[str]]
) -> list[Risk]:
    """Create risks for circular dependencies and dangling prerequisites."""
    task_by_id = {task.id: task for task in tasks}
    risks: list[Risk] = []

    for cycle in detect_cycles(graph):
        cycle_task_ids = cycle[:-1]
        labels = [_task_label(task_by_id, task_id) for task_id in cycle_task_ids]
        risks.append(
            Risk(
                related_task_ids=cycle_task_ids,
                severity=RiskSeverity.CRITICAL,
                explanation=(
                    f"Tasks {', '.join(labels)} form a circular dependency that must be "
                    "resolved before planning can proceed."
                ),
                recommended_response=(
                    "Review the dependency chain between these tasks and remove or correct "
                    "at least one prerequisite link."
                ),
            )
        )

    for task, prerequisite_id in _dangling_dependencies(tasks):
        risks.append(
            Risk(
                related_task_ids=[task.id],
                severity=RiskSeverity.MEDIUM,
                explanation=(
                    f"Task {task.title} references prerequisite {prerequisite_id}, "
                    "which does not exist in the current plan."
                ),
                recommended_response=(
                    "Verify the dependency was extracted correctly or re-upload the source "
                    "document."
                ),
            )
        )

    return risks


def recommend_next_action(
    tasks: list[AdministrativeTask], ordered_task_ids: list[str]
) -> AdministrativeTask | None:
    """Return the first ordered, not-started task with completed prerequisites."""
    task_by_id = {task.id: task for task in tasks}
    for task_id in ordered_task_ids:
        task = task_by_id.get(task_id)
        if task is None or task.status is not TaskStatus.NOT_STARTED:
            continue
        prerequisites_completed = all(
            task_by_id.get(dependency.prerequisite_task_id) is not None
            and task_by_id[dependency.prerequisite_task_id].status is TaskStatus.COMPLETED
            for dependency in task.dependencies
        )
        if prerequisites_completed:
            return task
    return None


def _risk_key(risk: Risk) -> tuple[tuple[str, ...], RiskSeverity, str]:
    normalized_explanation = " ".join(risk.explanation.casefold().split())
    return (tuple(sorted(risk.related_task_ids)), risk.severity, normalized_explanation)


def plan_goal(goal: AdministrativeGoal) -> AdministrativeGoal:
    """Plan a goal without mutating its input."""
    planned_goal = goal.model_copy(deep=True)
    graph = build_dependency_graph(planned_goal.tasks)
    ordered_task_ids, _ = topological_order(planned_goal.tasks)
    planning_risks = generate_planning_risks(planned_goal.tasks, graph)

    # Preserve existing risks while avoiding duplicate planning risks on repeated calls.
    existing_keys = {_risk_key(risk) for risk in planned_goal.risks}
    planned_goal.risks.extend(
        risk for risk in planning_risks if _risk_key(risk) not in existing_keys
    )

    next_task = recommend_next_action(planned_goal.tasks, ordered_task_ids)
    if next_task is None:
        planned_goal.next_action_summary = "No action is currently available for this goal."
    else:
        planned_goal.next_action_summary = f"Next recommended action: {next_task.title}."
    planned_goal.updated_at = datetime.now(timezone.utc)
    return planned_goal