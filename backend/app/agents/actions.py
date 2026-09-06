from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.agents.feasibility import FeasibilityReport, FeasibilityStatus
from app.agents.planner import recommend_next_action, topological_order
from app.models import (
    ActionProposal,
    ActionType,
    AdministrativeGoal,
    AdministrativeTask,
    ApprovalStatus,
    RiskSeverity,
    TaskStatus,
)


@dataclass(frozen=True)
class _Candidate:
    rank: int
    task_id: str
    action_type: ActionType
    purpose: str
    description: str
    generated_content: str | None
    deadline: datetime | None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return value.astimezone(timezone.utc)


def _task_map(goal: AdministrativeGoal) -> dict[str, AdministrativeTask]:
    return {task.id: task for task in goal.tasks}


def _deadline_key(deadline: datetime | None) -> tuple[int, float]:
    if deadline is None:
        return (1, 0.0)
    return (0, deadline.timestamp())


def _draft(subject: str, body: str) -> str:
    return f"Subject: {subject}\n\nHello [recipient],\n\n{body}\n\nRegards,\n[Your name]"


def _candidate_for_issue(
    task: AdministrativeTask,
    issue_type: str,
    explanation: str,
    rank: int,
    critical_path: set[str],
) -> _Candidate | None:
    if task.status is TaskStatus.COMPLETED:
        return None
    if issue_type in {"BLOCKED_TASK", "DEPENDENCY_CYCLE"} or task.status in (
        TaskStatus.BLOCKED,
        TaskStatus.REJECTED,
    ):
        responsible = (
            f" The responsible party is {task.responsible_party}."
            if task.responsible_party
            else ""
        )
        action_rank = 0 if task.id in critical_path else 1
        return _Candidate(
            action_rank,
            task.id,
            ActionType.REQUEST_INFO,
            "resolve_blocker",
            f'Threadline recommends resolving the blocker for "{task.title}" because '
            f"{explanation}.{responsible} Approval is required before requesting information or contacting anyone.",
            _draft(
                f"Request assistance with {task.title}",
                f"I need help resolving the issue affecting {task.title}. {explanation}. "
                "Could you clarify the required next step or information?",
            ),
            task.deadline,
        )
    if issue_type in {"DEADLINE_MISS", "OVERDUE_TASK"}:
        return _Candidate(
            1,
            task.id,
            ActionType.ESCALATION,
            "deadline_recovery",
            f'Threadline recommends escalating "{task.title}" because {explanation}. '
            "Approval is required before requesting assistance or an extension.",
            _draft(
                f"Request assistance with {task.title}",
                f"I am reviewing {task.title}, which needs recovery because {explanation}. "
                "Could you advise on available options or whether an extension request is appropriate?",
            ),
            task.deadline,
        )
    if issue_type == "LOW_CONFIDENCE":
        sources = ", ".join(task.source_ids) if task.source_ids else "the cited source"
        return _Candidate(
            3,
            task.id,
            ActionType.REQUEST_INFO,
            "verify_requirement",
            f'Threadline recommends verifying "{task.title}" against {sources} because '
            f"{explanation}. Approval is required before requesting clarification.",
            _draft(
                f"Clarification needed for {task.title}",
                f"I am reviewing the requirement for {task.title}. {explanation} "
                "Could you confirm the applicable requirement or source guidance?",
            ),
            task.deadline,
        )
    return None


def _existing_keys(goal: AdministrativeGoal) -> set[tuple[str, ActionType, str]]:
    keys: set[tuple[str, ActionType, str]] = set()
    for proposal in goal.proposed_actions:
        purpose = "unknown"
        if "blocker" in proposal.description.casefold():
            purpose = "resolve_blocker"
        elif "deadline" in proposal.description.casefold() or "overdue" in proposal.description.casefold():
            purpose = "deadline_recovery"
        elif "verif" in proposal.description.casefold():
            purpose = "verify_requirement"
        elif proposal.action_type is ActionType.REMINDER:
            purpose = "next_action"
        keys.add((proposal.related_task_id, proposal.action_type, purpose))
    return keys


def _add_candidate(
    candidates: dict[tuple[str, ActionType, str], _Candidate], candidate: _Candidate | None
) -> None:
    if candidate is None:
        return
    key = (candidate.task_id, candidate.action_type, candidate.purpose)
    candidates.setdefault(key, candidate)


def generate_action_proposals(
    goal: AdministrativeGoal,
    feasibility_report: FeasibilityReport | None,
    as_of: datetime,
    max_proposals: int = 5,
) -> list[ActionProposal]:
    """Generate deterministic, approval-required proposals without mutating ``goal``."""
    if max_proposals < 0:
        raise ValueError("max_proposals must not be negative")
    if max_proposals == 0:
        return []
    created_at = _utc(as_of)
    task_by_id = _task_map(goal)
    critical_path = (
        set(feasibility_report.critical_path_task_ids) if feasibility_report else set()
    )
    candidates: dict[tuple[str, ActionType, str], _Candidate] = {}
    existing = _existing_keys(goal)
    urgent_task_ids: set[str] = set()

    if feasibility_report is not None:
        for issue in feasibility_report.detected_issues:
            if issue.issue_type in {"DEADLINE_MISS", "OVERDUE_TASK", "BLOCKED_TASK", "DEPENDENCY_CYCLE"}:
                urgent_task_ids.update(issue.related_task_ids)
            for task_id in issue.related_task_ids:
                task = task_by_id.get(task_id)
                if task is None:
                    continue
                _add_candidate(
                    candidates,
                    _candidate_for_issue(
                        task,
                        issue.issue_type,
                        issue.explanation,
                        1,
                        critical_path,
                    ),
                )

        if feasibility_report.overall_status is FeasibilityStatus.AT_RISK:
            for projection in feasibility_report.task_projections:
                task = task_by_id.get(projection.task_id)
                if (
                    task is not None
                    and task.status is not TaskStatus.COMPLETED
                    and projection.available_slack_days is not None
                    and projection.available_slack_days <= 2
                    and projection.feasible
                ):
                    _add_candidate(
                        candidates,
                        _Candidate(
                            2 if projection.available_slack_days <= 0 else 3,
                            task.id,
                            ActionType.REMINDER,
                            "low_slack",
                            f'Threadline recommends completing "{task.title}" promptly because '
                            f"only {projection.available_slack_days:g} day(s) of slack remain. "
                            "Approval is required before sending a reminder.",
                            None,
                            task.deadline,
                        ),
                    )

        if feasibility_report.overall_status is FeasibilityStatus.INFEASIBLE:
            fallback_ids = [
                task_id for task_id in feasibility_report.critical_path_task_ids
                if task_id in task_by_id
            ] or [
                task.id for task in goal.tasks if task.status is not TaskStatus.COMPLETED
            ]
            if fallback_ids:
                fallback_task = task_by_id[fallback_ids[0]]
                _add_candidate(
                    candidates,
                    _Candidate(
                        1,
                        fallback_task.id,
                        ActionType.ESCALATION,
                        "deadline_recovery",
                        f'Threadline recommends escalation for "{fallback_task.title}" because '
                        f"the feasibility report marks the goal infeasible: {feasibility_report.summary} "
                        "Approval is required before requesting assistance or an extension.",
                        _draft(
                            f"Request assistance with {fallback_task.title}",
                            f"The current plan is not feasible because {feasibility_report.summary} "
                            "Could you advise on available options or whether an extension request is appropriate?",
                        ),
                        fallback_task.deadline,
                    ),
                )

    blocked_or_rejected = {
        task.id
        for task in goal.tasks
        if task.status in (TaskStatus.BLOCKED, TaskStatus.REJECTED)
    }
    for task_id in blocked_or_rejected:
        _add_candidate(
            candidates,
            _candidate_for_issue(
                task_by_id[task_id],
                "BLOCKED_TASK",
                f'the task is {task_by_id[task_id].status.value}',
                0,
                critical_path,
            ),
        )

    ordered_ids, _ = topological_order(goal.tasks)
    next_task = recommend_next_action(goal.tasks, ordered_ids)
    if next_task is not None and next_task.id not in urgent_task_ids:
        deadline_text = (
            f" The task deadline is {next_task.deadline.isoformat()}."
            if next_task.deadline
            else ""
        )
        _add_candidate(
            candidates,
            _Candidate(
                4,
                next_task.id,
                ActionType.REMINDER,
                "next_action",
                f'Threadline recommends taking the next step on "{next_task.title}".{deadline_text} '
                "Approval is required before sending a reminder.",
                None,
                next_task.deadline,
            ),
        )

    filtered = [
        candidate
        for key, candidate in candidates.items()
        if key not in existing
        and task_by_id[candidate.task_id].status is not TaskStatus.COMPLETED
    ]
    filtered.sort(key=lambda item: (item.rank, _deadline_key(item.deadline), item.task_id, item.purpose))
    return [
        ActionProposal(
            related_task_id=candidate.task_id,
            action_type=candidate.action_type,
            description=candidate.description,
            generated_content=candidate.generated_content,
            requires_approval=True,
            approval_status=ApprovalStatus.PENDING,
            created_at=created_at,
        )
        for candidate in filtered[:max_proposals]
    ]


def add_action_proposals(
    goal: AdministrativeGoal, proposals: list[ActionProposal]
) -> AdministrativeGoal:
    """Return a copied goal with proposals appended, without executing anything."""
    updated_goal = goal.model_copy(deep=True)
    existing = _existing_keys(updated_goal)
    for proposal in proposals:
        key = (proposal.related_task_id, proposal.action_type, "unknown")
        if any(
            existing_key[:2] == key[:2] for existing_key in existing
        ):
            continue
        updated_goal.proposed_actions.append(proposal.model_copy(deep=True))
        existing.add(key)
    return updated_goal


def review_action_proposal(
    goal: AdministrativeGoal,
    action_id: str,
    decision: ApprovalStatus | str,
    edited_content: str | None = None,
) -> AdministrativeGoal:
    """Approve or reject a pending proposal in a copied goal; never execute it."""
    if isinstance(decision, ApprovalStatus):
        normalized_decision = decision
    else:
        try:
            normalized_decision = ApprovalStatus(decision.lower())
        except (AttributeError, ValueError) as error:
            raise ValueError("decision must be approved or rejected") from error
    if normalized_decision not in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED):
        raise ValueError("decision must be approved or rejected")

    updated_goal = goal.model_copy(deep=True)
    proposal = next(
        (item for item in updated_goal.proposed_actions if item.id == action_id), None
    )
    if proposal is None:
        raise ValueError(f"Action proposal with id '{action_id}' was not found")
    if proposal.approval_status is not ApprovalStatus.PENDING:
        raise ValueError("already reviewed action proposals cannot be changed")

    if normalized_decision is ApprovalStatus.APPROVED and edited_content is not None:
        proposal.generated_content = edited_content
    proposal.approval_status = normalized_decision
    return updated_goal