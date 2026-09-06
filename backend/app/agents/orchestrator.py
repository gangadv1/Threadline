from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from app.agents.actions import (
    add_action_proposals,
    generate_action_proposals,
)
from app.agents.feasibility import FeasibilityReport, analyze_goal_feasibility
from app.agents.planner import (
    plan_goal,
    recommend_next_action,
    topological_order,
)
from app.agents.replanner import (
    find_downstream_tasks,
    replan_after_disruption,
)
from app.models import AdministrativeGoal, TaskStatus


class AgentPhase(str, Enum):
    PLAN = "plan"
    ANALYSE = "analyse"
    ACT = "act"
    ADAPT = "adapt"


class AgentStepRecord(BaseModel):
    phase: AgentPhase
    short_title: str
    explanation: str
    related_task_ids: list[str] = Field(default_factory=list)
    timestamp: datetime


class AgentCycleResult(BaseModel):
    updated_goal: AdministrativeGoal
    ordered_task_ids: list[str] = Field(default_factory=list)
    recommended_next_task_id: str | None = None
    feasibility_report: FeasibilityReport
    newly_generated_action_ids: list[str] = Field(default_factory=list)
    step_records: list[AgentStepRecord] = Field(default_factory=list)
    replanning_occurred: bool = False
    disruption_summary: str | None = None
    cycle_timestamp: datetime


def _validate_inputs(as_of: datetime, max_proposals: int) -> datetime:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if max_proposals < 0:
        raise ValueError("max_proposals must not be negative")
    return as_of.astimezone(timezone.utc)


def _step(
    phase: AgentPhase,
    title: str,
    explanation: str,
    related_task_ids: list[str],
    timestamp: datetime,
) -> AgentStepRecord:
    return AgentStepRecord(
        phase=phase,
        short_title=title,
        explanation=explanation,
        related_task_ids=related_task_ids,
        timestamp=timestamp,
    )


def _complete_cycle(
    planned_goal: AdministrativeGoal,
    as_of: datetime,
    max_proposals: int,
    steps: list[AgentStepRecord],
    disruption_summary: str | None,
    replanning_occurred: bool,
) -> AgentCycleResult:
    ordered_task_ids, _ = topological_order(planned_goal.tasks)
    next_task = recommend_next_action(planned_goal.tasks, ordered_task_ids)
    steps.append(
        _step(
            AgentPhase.PLAN,
            "Plan tasks",
            f"Created an order for {len(ordered_task_ids)} task(s).",
            ordered_task_ids,
            as_of,
        )
    )

    feasibility_report = analyze_goal_feasibility(planned_goal, as_of)
    steps.append(
        _step(
            AgentPhase.ANALYSE,
            "Analyse feasibility",
            feasibility_report.summary,
            feasibility_report.critical_path_task_ids,
            as_of,
        )
    )

    before_ids = {proposal.id for proposal in planned_goal.proposed_actions}
    proposals = generate_action_proposals(
        planned_goal, feasibility_report, as_of, max_proposals=max_proposals
    )
    final_goal = add_action_proposals(planned_goal, proposals)
    new_action_ids = [
        proposal.id
        for proposal in final_goal.proposed_actions
        if proposal.id not in before_ids
    ]
    if new_action_ids:
        steps.append(
            _step(
                AgentPhase.ACT,
                "Prepare action proposals",
                f"Prepared {len(new_action_ids)} action proposal(s) for human review.",
                [proposal.related_task_id for proposal in proposals if proposal.id in new_action_ids],
                as_of,
            )
        )

    return AgentCycleResult(
        updated_goal=final_goal,
        ordered_task_ids=ordered_task_ids,
        recommended_next_task_id=next_task.id if next_task is not None else None,
        feasibility_report=feasibility_report,
        newly_generated_action_ids=new_action_ids,
        step_records=steps,
        replanning_occurred=replanning_occurred,
        disruption_summary=disruption_summary,
        cycle_timestamp=as_of,
    )


def run_agent_cycle(
    goal: AdministrativeGoal, as_of: datetime, max_proposals: int = 5
) -> AgentCycleResult:
    """Run PLAN, ANALYSE, and ACT without mutating ``goal``."""
    cycle_time = _validate_inputs(as_of, max_proposals)
    planned_goal = plan_goal(goal)
    return _complete_cycle(
        planned_goal,
        cycle_time,
        max_proposals,
        [],
        disruption_summary=None,
        replanning_occurred=False,
    )


def run_disruption_cycle(
    goal: AdministrativeGoal,
    task_id: str,
    new_status: TaskStatus,
    as_of: datetime,
    new_deadline: datetime | None = None,
    reason: str | None = None,
    max_proposals: int = 5,
) -> AgentCycleResult:
    """Apply a disruption through the replanner, then run ANALYSE and ACT again."""
    cycle_time = _validate_inputs(as_of, max_proposals)
    downstream_task_ids = find_downstream_tasks(task_id, goal.tasks)
    planned_goal, disruption_summary = replan_after_disruption(
        goal,
        task_id,
        new_status=new_status,
        new_deadline=new_deadline,
    )
    if reason:
        disruption_summary = f"{disruption_summary}\nReason: {reason}"
    affected_ids = [task_id, *downstream_task_ids]
    steps = [
        _step(
            AgentPhase.ADAPT,
            "Process disruption",
            disruption_summary,
            affected_ids,
            cycle_time,
        )
    ]
    return _complete_cycle(
        planned_goal,
        cycle_time,
        max_proposals,
        steps,
        disruption_summary=disruption_summary,
        replanning_occurred=True,
    )