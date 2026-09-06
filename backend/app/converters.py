"""
app/converters.py
==================
Bridges the AI extraction layer (`app.extraction`, which knows nothing
about planning/feasibility) and the agent/workflow layer (`app.models`,
`app.agents`, which know nothing about AI extraction).

    Documents -> extraction.ExtractionResult -> [this file] -> AdministrativeGoal
        -> app.agents.run_agent_cycle() -> feasibility/risks/action proposals

`AdministrativeTask` has no `category` or `required_documents` fields, so
those are folded into the task description (still visible to the student
and to the extraction-confidence/feasibility logic) rather than silently
dropped.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.extraction.schemas import ExtractionResult
from app.extraction.schemas import Task as ExtractedTask
from app.models import AdministrativeGoal, AdministrativeTask, DocumentSource, Priority, TaskDependency

_PRIORITY_MAP = {
    "high": Priority.HIGH,
    "medium": Priority.MEDIUM,
    "low": Priority.LOW,
}


def _parse_deadline(deadline: str | None) -> datetime | None:
    """Extraction deadlines are plain YYYY-MM-DD strings; treat them as due
    by end-of-day UTC so they compare sensibly against `datetime.now(utc)`."""
    if not deadline:
        return None
    parsed = datetime.fromisoformat(deadline)
    parsed = parsed.replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
    return parsed


def _describe(task: ExtractedTask) -> str:
    parts = [task.description]
    if task.required_documents:
        parts.append(f"Required documents: {', '.join(task.required_documents)}.")
    category_label = task.category.value.replace("_", " ").title()
    return f"[{category_label}] " + " ".join(parts)


def extraction_result_to_goal(
    extraction: ExtractionResult,
    *,
    title: str,
    description: str | None = None,
    final_deadline: datetime | None = None,
    document: DocumentSource | None = None,
) -> AdministrativeGoal:
    """Convert a raw extraction result into a persistable AdministrativeGoal.

    Does not run planning/feasibility - call `app.agents.run_agent_cycle()`
    on the result afterwards (this is exactly what POST /goals/{id}/cycle
    does, so a freshly-created goal just needs that endpoint called once).
    """
    documents = [document] if document is not None else []
    source_ids = [document.id] if document is not None else []

    tasks: list[AdministrativeTask] = []
    name_to_id: dict[str, str] = {}
    for extracted in extraction.tasks:
        task = AdministrativeTask(
            title=extracted.task_name,
            description=_describe(extracted),
            priority=_PRIORITY_MAP.get(extracted.priority.value, Priority.MEDIUM),
            deadline=_parse_deadline(extracted.deadline),
            source_ids=list(source_ids),
            confidence=1.0 if extracted.deadline_is_explicit or extracted.deadline is None else 0.85,
        )
        tasks.append(task)
        name_to_id[extracted.task_name] = task.id

    for extracted, task in zip(extraction.tasks, tasks):
        for dependency_name in extracted.dependencies:
            prerequisite_id = name_to_id.get(dependency_name)
            if prerequisite_id is None or prerequisite_id == task.id:
                # Either the model referenced a task name that doesn't exist
                # in its own output, or (degenerately) referenced itself.
                # The planner's dangling-dependency risk check exists for
                # the former; silently drop the latter to avoid a Pydantic
                # validation error on self-dependency.
                if prerequisite_id != task.id:
                    task.dependencies.append(
                        TaskDependency(
                            prerequisite_task_id=dependency_name,
                            reason="Inferred by the extraction model; task not found in this plan.",
                        )
                    )
                continue
            task.dependencies.append(
                TaskDependency(
                    prerequisite_task_id=prerequisite_id,
                    reason=f'Must be completed before "{task.title}" can start.',
                )
            )

    goal_description = description or ""
    if extraction.extraction_notes:
        note = f"Extraction notes: {extraction.extraction_notes}"
        goal_description = f"{goal_description}\n\n{note}".strip()

    return AdministrativeGoal(
        title=title,
        description=goal_description,
        final_deadline=final_deadline,
        documents=documents,
        tasks=tasks,
    )
