from datetime import datetime, timezone

from app.agents.planner import plan_goal
from app.models import AdministrativeGoal, AdministrativeTask, TaskStatus


def find_downstream_tasks(
    task_id: str, tasks: list[AdministrativeTask]
) -> list[str]:
    """Return all transitive dependents of a task in deterministic order."""
    dependents: dict[str, list[str]] = {task.id: [] for task in tasks}
    for task in tasks:
        for dependency in task.dependencies:
            if dependency.prerequisite_task_id in dependents:
                dependents[dependency.prerequisite_task_id].append(task.id)

    downstream: list[str] = []
    visited: set[str] = {task_id}
    pending = list(dependents.get(task_id, []))
    while pending:
        dependent_id = pending.pop(0)
        if dependent_id in visited:
            continue
        visited.add(dependent_id)
        downstream.append(dependent_id)
        pending.extend(dependents.get(dependent_id, []))
    return downstream


def apply_disruption(
    goal: AdministrativeGoal,
    task_id: str,
    new_status: TaskStatus | None = None,
    new_deadline: datetime | None = None,
) -> tuple[AdministrativeGoal, list[str]]:
    """Apply a task disruption to a deep copy and block affected dependents."""
    updated_goal = goal.model_copy(deep=True)
    disrupted_task = next(
        (task for task in updated_goal.tasks if task.id == task_id), None
    )
    if disrupted_task is None:
        raise ValueError(f"Task with id '{task_id}' was not found in the goal")

    if new_status is not None:
        disrupted_task.status = new_status
    if new_deadline is not None:
        disrupted_task.deadline = new_deadline
    if new_status is not None or new_deadline is not None:
        disrupted_task.updated_at = datetime.now(timezone.utc)

    downstream_task_ids = find_downstream_tasks(task_id, updated_goal.tasks)
    if new_status in (TaskStatus.REJECTED, TaskStatus.BLOCKED):
        downstream_ids = set(downstream_task_ids)
        for task in updated_goal.tasks:
            if task.id in downstream_ids and task.status is not TaskStatus.COMPLETED:
                task.status = TaskStatus.BLOCKED
                task.updated_at = datetime.now(timezone.utc)

    updated_goal.updated_at = datetime.now(timezone.utc)
    return updated_goal, downstream_task_ids


def _format_deadline(deadline: datetime) -> str:
    return deadline.isoformat()


def summarize_changes(
    original_goal: AdministrativeGoal,
    updated_goal: AdministrativeGoal,
    disrupted_task_id: str,
    downstream_task_ids: list[str],
) -> str:
    """Describe the disruption and its downstream impact using task titles."""
    original_task = next(
        task for task in original_goal.tasks if task.id == disrupted_task_id
    )
    updated_task = next(
        task for task in updated_goal.tasks if task.id == disrupted_task_id
    )
    lines = [f'Task "{updated_task.title}" was updated.']

    if original_task.status != updated_task.status:
        lines[0] = (
            f'Task "{updated_task.title}" was marked as '
            f"{updated_task.status.value.replace('_', ' ')}."
        )
    if original_task.deadline != updated_task.deadline and updated_task.deadline is not None:
        lines.append(f"New deadline: {_format_deadline(updated_task.deadline)}.")

    if not downstream_task_ids:
        lines.append("No other tasks are affected.")
        return "\n".join(lines)

    task_titles = {
        task.id: task.title for task in updated_goal.tasks
    }
    affected_titles = [task_titles[task_id] for task_id in downstream_task_ids]
    blocked_titles = [
        task_titles[task_id]
        for task_id in downstream_task_ids
        if next(task for task in updated_goal.tasks if task.id == task_id).status
        is TaskStatus.BLOCKED
    ]
    lines.append(
        f"This affects {len(downstream_task_ids)} downstream task(s): "
        f"{', '.join(f'\"{title}\"' for title in affected_titles)}."
    )
    if blocked_titles:
        lines.append(
            f"The affected task(s) now marked as blocked: "
            f"{', '.join(f'\"{title}\"' for title in blocked_titles)}."
        )
    return "\n".join(lines)


def replan_after_disruption(
    goal: AdministrativeGoal,
    task_id: str,
    new_status: TaskStatus | None = None,
    new_deadline: datetime | None = None,
) -> tuple[AdministrativeGoal, str]:
    """Apply a disruption, re-run planning, and return a change explanation."""
    updated_goal, downstream_task_ids = apply_disruption(
        goal, task_id, new_status=new_status, new_deadline=new_deadline
    )
    final_goal = plan_goal(updated_goal)
    summary = summarize_changes(
        goal, final_goal, task_id, downstream_task_ids
    )
    return final_goal, summary