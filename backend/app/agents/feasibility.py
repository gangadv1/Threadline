from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum

from pydantic import BaseModel, Field

from app.models import AdministrativeGoal, AdministrativeTask, RiskSeverity, TaskStatus


class FeasibilityStatus(str, Enum):
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    INFEASIBLE = "infeasible"
    COMPLETED = "completed"
    INSUFFICIENT_INFORMATION = "insufficient_information"


class TaskProjection(BaseModel):
    task_id: str
    task_title: str
    earliest_possible_start: datetime | None = None
    projected_completion_date: datetime | None = None
    effective_deadline: datetime | None = None
    available_slack_days: float | None = None
    feasible: bool
    dependency_ids_affecting_start: list[str] = Field(default_factory=list)
    explanation: str


class FeasibilityIssue(BaseModel):
    related_task_ids: list[str] = Field(default_factory=list)
    severity: RiskSeverity
    issue_type: str
    explanation: str
    recommended_response: str


class FeasibilityReport(BaseModel):
    goal_id: str
    analysis_timestamp: datetime
    overall_status: FeasibilityStatus
    projected_goal_completion_date: datetime | None = None
    final_deadline: datetime | None = None
    remaining_slack_days: float | None = None
    task_projections: list[TaskProjection] = Field(default_factory=list)
    detected_issues: list[FeasibilityIssue] = Field(default_factory=list)
    critical_path_task_ids: list[str] = Field(default_factory=list)
    summary: str


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of and model deadlines must be timezone-aware")
    return value.astimezone(timezone.utc)


def _effective_deadline(
    task: AdministrativeTask, goal_deadline: datetime | None
) -> datetime | None:
    task_deadline = _ensure_utc(task.deadline) if task.deadline is not None else None
    deadlines = [deadline for deadline in (task_deadline, goal_deadline) if deadline is not None]
    return min(deadlines) if deadlines else None


def _issue(
    task_ids: list[str],
    severity: RiskSeverity,
    issue_type: str,
    explanation: str,
    response: str,
) -> FeasibilityIssue:
    return FeasibilityIssue(
        related_task_ids=task_ids,
        severity=severity,
        issue_type=issue_type,
        explanation=explanation,
        recommended_response=response,
    )


def _cycle_ids(tasks: list[AdministrativeTask]) -> set[str]:
    task_by_id = {task.id: task for task in tasks}
    state: dict[str, int] = {}
    stack: list[str] = []
    cyclic: set[str] = set()

    def visit(task_id: str) -> None:
        state[task_id] = 1
        stack.append(task_id)
        for dependency in task_by_id[task_id].dependencies:
            if dependency.prerequisite_task_id not in task_by_id:
                continue
            prerequisite = dependency.prerequisite_task_id
            if state.get(prerequisite, 0) == 0:
                visit(prerequisite)
            elif state.get(prerequisite) == 1:
                cyclic.update(stack[stack.index(prerequisite) :])
        stack.pop()
        state[task_id] = 2

    for task in tasks:
        if state.get(task.id, 0) == 0:
            visit(task.id)
    return cyclic


def _critical_path(
    tasks: list[AdministrativeTask],
    projections: dict[str, TaskProjection],
) -> list[str]:
    incomplete = {task.id for task in tasks if task.status is not TaskStatus.COMPLETED}
    candidates = [
        task_id
        for task_id in incomplete
        if projections[task_id].projected_completion_date is not None
    ]
    if not candidates:
        return []

    task_by_id = {task.id: task for task in tasks}
    endpoint = max(
        candidates,
        key=lambda task_id: projections[task_id].projected_completion_date,
    )
    path: list[str] = []
    current = endpoint
    while current not in path:
        path.append(current)
        task = task_by_id[current]
        influencing = [
            dependency.prerequisite_task_id
            for dependency in task.dependencies
            if dependency.prerequisite_task_id in incomplete
            and projections[dependency.prerequisite_task_id].projected_completion_date
            is not None
        ]
        if not influencing:
            break
        current = max(
            influencing,
            key=lambda task_id: projections[task_id].projected_completion_date,
        )
    path.reverse()
    return path


def analyze_goal_feasibility(
    goal: AdministrativeGoal, as_of: datetime
) -> FeasibilityReport:
    """Project task completion using dependency timing without mutating ``goal``."""
    analysis_time = _ensure_utc(as_of)
    goal_deadline = (
        _ensure_utc(goal.final_deadline) if goal.final_deadline is not None else None
    )
    tasks = goal.model_copy(deep=True).tasks
    task_by_id = {task.id: task for task in tasks}
    projections: dict[str, TaskProjection] = {}
    issues: list[FeasibilityIssue] = []
    visiting: set[str] = set()
    cycle_ids = _cycle_ids(tasks)

    for task in tasks:
        for dependency in task.dependencies:
            if dependency.prerequisite_task_id not in task_by_id:
                issues.append(
                    _issue(
                        [task.id],
                        RiskSeverity.MEDIUM,
                        "MISSING_DEPENDENCY",
                        f'Task "{task.title}" references prerequisite '
                        f'"{dependency.prerequisite_task_id}" which is not in the plan.',
                        "Verify the dependency against the source document.",
                    )
                )

    def project(task_id: str) -> TaskProjection:
        if task_id in projections:
            return projections[task_id]
        task = task_by_id[task_id]
        deadline = _effective_deadline(task, goal_deadline)
        if task.status is TaskStatus.COMPLETED:
            projection = TaskProjection(
                task_id=task.id,
                task_title=task.title,
                earliest_possible_start=analysis_time,
                projected_completion_date=analysis_time,
                effective_deadline=deadline,
                available_slack_days=(
                    (deadline - analysis_time).total_seconds() / 86400
                    if deadline is not None
                    else None
                ),
                feasible=True,
                explanation=f'Task "{task.title}" is already completed.',
            )
            projections[task_id] = projection
            return projection

        if task_id in visiting or task_id in cycle_ids:
            projection = TaskProjection(
                task_id=task.id,
                task_title=task.title,
                effective_deadline=deadline,
                feasible=False,
                explanation=f'Task "{task.title}" is part of a dependency cycle.',
            )
            projections[task_id] = projection
            return projection

        visiting.add(task_id)
        prerequisite_projections: list[tuple[str, TaskProjection]] = []
        missing_prerequisites: list[str] = []
        for dependency in task.dependencies:
            prerequisite_id = dependency.prerequisite_task_id
            if prerequisite_id not in task_by_id:
                missing_prerequisites.append(prerequisite_id)
            else:
                prerequisite_projections.append((prerequisite_id, project(prerequisite_id)))
        visiting.remove(task_id)

        affecting_ids = [
            prerequisite_id
            for prerequisite_id, prerequisite in prerequisite_projections
            if prerequisite.projected_completion_date is not None
            and prerequisite.projected_completion_date
            == max(
                item.projected_completion_date
                for _, item in prerequisite_projections
                if item.projected_completion_date is not None
            )
        ]
        starts = [analysis_time]
        starts.extend(
            prerequisite.projected_completion_date
            for _, prerequisite in prerequisite_projections
            if prerequisite.projected_completion_date is not None
        )
        earliest_start = max(starts)
        if task.status in (TaskStatus.BLOCKED, TaskStatus.REJECTED):
            projection = TaskProjection(
                task_id=task.id,
                task_title=task.title,
                earliest_possible_start=earliest_start,
                effective_deadline=deadline,
                feasible=False,
                dependency_ids_affecting_start=affecting_ids,
                explanation=f'Task "{task.title}" is {task.status.value} and has no valid completion projection.',
            )
            issues.append(
                _issue(
                    [task.id],
                    RiskSeverity.CRITICAL,
                    "BLOCKED_TASK",
                    f'Task "{task.title}" is {task.status.value}; downstream completion cannot be reliably projected.',
                    "Resolve the blocked prerequisite or contact the responsible party.",
                )
            )
        elif missing_prerequisites or any(
            prerequisite.projected_completion_date is None
            for _, prerequisite in prerequisite_projections
        ):
            projection = TaskProjection(
                task_id=task.id,
                task_title=task.title,
                earliest_possible_start=earliest_start,
                effective_deadline=deadline,
                feasible=False,
                dependency_ids_affecting_start=affecting_ids,
                explanation=f'Task "{task.title}" cannot be projected because prerequisite timing is incomplete.',
            )
        elif task.estimated_processing_time_days is None:
            projection = TaskProjection(
                task_id=task.id,
                task_title=task.title,
                earliest_possible_start=earliest_start,
                effective_deadline=deadline,
                feasible=False,
                dependency_ids_affecting_start=affecting_ids,
                explanation=f'Task "{task.title}" has no processing-time estimate; completion timing is uncertain.',
            )
            issues.append(
                _issue(
                    [task.id],
                    RiskSeverity.MEDIUM,
                    "MISSING_PROCESSING_TIME",
                    f'Task "{task.title}" has no processing-time estimate, so feasibility cannot be determined precisely.',
                    "Obtain an estimate from the responsible party or source document.",
                )
            )
        else:
            completion = earliest_start + timedelta(days=task.estimated_processing_time_days)
            slack = (
                (deadline - completion).total_seconds() / 86400
                if deadline is not None
                else None
            )
            feasible = deadline is None or completion <= deadline
            projection = TaskProjection(
                task_id=task.id,
                task_title=task.title,
                earliest_possible_start=earliest_start,
                projected_completion_date=completion,
                effective_deadline=deadline,
                available_slack_days=slack,
                feasible=feasible,
                dependency_ids_affecting_start=affecting_ids,
                explanation=(
                    f'Task "{task.title}" can finish by {completion.isoformat()}.'
                    if feasible
                    else f'Task "{task.title}" is projected to finish after its effective deadline.'
                ),
            )
            if deadline is not None and completion > deadline:
                issues.append(
                    _issue(
                        [task.id],
                        RiskSeverity.CRITICAL,
                        "DEADLINE_MISS",
                        f'Task "{task.title}" is projected to finish after its effective deadline.',
                        "Complete the task sooner, contact the responsible party, or seek an extension.",
                    )
                )

        projections[task_id] = projection
        if task.deadline is not None and task.status is not TaskStatus.COMPLETED:
            task_deadline = _ensure_utc(task.deadline)
            if task_deadline < analysis_time:
                issues.append(
                    _issue(
                        [task.id],
                        RiskSeverity.CRITICAL,
                        "OVERDUE_TASK",
                        f'Task "{task.title}" has an incomplete deadline before the analysis date.',
                        "Contact the responsible party immediately and seek an extension if needed.",
                    )
                )
        if task.confidence < 0.70:
            issues.append(
                _issue(
                    [task.id],
                    RiskSeverity.MEDIUM,
                    "LOW_CONFIDENCE",
                    f'Task "{task.title}" has low extraction confidence ({task.confidence:.2f}).',
                    "Verify this requirement against its source document.",
                )
            )
        return projection

    for task in tasks:
        project(task.id)

    if cycle_ids:
        issues.append(
            _issue(
                sorted(cycle_ids),
                RiskSeverity.CRITICAL,
                "DEPENDENCY_CYCLE",
                "Some tasks form a dependency cycle and cannot be scheduled reliably.",
                "Remove or correct a prerequisite link in the cycle.",
            )
        )

    if goal_deadline is None and incomplete_tasks:
        issues.append(
            _issue(
                [task.id for task in incomplete_tasks],
                RiskSeverity.MEDIUM,
                "MISSING_GOAL_DEADLINE",
                "The goal has no final deadline, so overall completion feasibility cannot be determined precisely.",
                "Confirm the final submission deadline from the source instructions.",
            )
        )

    incomplete_tasks = [task for task in tasks if task.status is not TaskStatus.COMPLETED]
    projected_dates = [
        projection.projected_completion_date
        for projection in projections.values()
        if projection.projected_completion_date is not None
    ]
    projected_goal_completion = max(projected_dates) if projected_dates else None
    critical_path = _critical_path(tasks, projections)
    remaining_slack = (
        (goal_deadline - projected_goal_completion).total_seconds() / 86400
        if goal_deadline is not None and projected_goal_completion is not None
        else None
    )

    has_critical_issue = any(
        issue.severity is RiskSeverity.CRITICAL for issue in issues
    )
    has_uncertainty = any(
        issue.issue_type
        in {"MISSING_PROCESSING_TIME", "MISSING_DEPENDENCY", "MISSING_GOAL_DEADLINE"}
        for issue in issues
    ) or any(
        projection.projected_completion_date is None
        for projection in projections.values()
        if projection.task_id in {task.id for task in incomplete_tasks}
    )
    has_low_confidence = any(issue.issue_type == "LOW_CONFIDENCE" for issue in issues)
    low_slack = remaining_slack is not None and remaining_slack <= 2

    if not incomplete_tasks:
        status = FeasibilityStatus.COMPLETED
        summary = "All tasks are completed."
    elif has_critical_issue:
        status = FeasibilityStatus.INFEASIBLE
        summary = "The remaining plan is not feasible without resolving critical issues."
    elif has_uncertainty:
        status = FeasibilityStatus.INSUFFICIENT_INFORMATION
        summary = "Feasibility cannot be determined reliably because timing information is missing."
    elif has_low_confidence or low_slack:
        status = FeasibilityStatus.AT_RISK
        summary = "The plan is currently feasible but has limited slack or low-confidence requirements."
    else:
        status = FeasibilityStatus.ON_TRACK
        summary = "The remaining plan is projected to complete before the final deadline."

    return FeasibilityReport(
        goal_id=goal.id,
        analysis_timestamp=analysis_time,
        overall_status=status,
        projected_goal_completion_date=projected_goal_completion,
        final_deadline=goal_deadline,
        remaining_slack_days=remaining_slack,
        task_projections=[projections[task.id] for task in tasks],
        detected_issues=issues,
        critical_path_task_ids=critical_path,
        summary=summary,
    )