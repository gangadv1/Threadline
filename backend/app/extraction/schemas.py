"""
app/extraction/schemas.py
==========================
The EXACT shape of the JSON the AI extraction model returns. This is
intentionally separate from `app.models` (the AdministrativeGoal workflow
schema) and from `app.api.schemas` (the API wire formats) - extraction
output gets converted into an AdministrativeGoal by
`app.converters.extraction_result_to_goal` before it ever touches the
planning/feasibility/persistence layers.
"""

from __future__ import annotations
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class Priority(str, Enum):
    """How urgent/important this task is, as judged by the AI."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Category(str, Enum):
    """Broad bucket so the frontend can color-code / filter tasks."""
    VISA_IMMIGRATION = "visa_immigration"
    HOUSING = "housing"
    FINANCE_PAYMENT = "finance_payment"
    ACADEMIC_ENROLLMENT = "academic_enrollment"
    HEALTH_INSURANCE = "health_insurance"
    ORIENTATION_EVENT = "orientation_event"
    OTHER = "other"


class Task(BaseModel):
    """A single actionable task extracted from a messy email/PDF."""

    task_name: str = Field(
        description=(
            "A short, clear, action-oriented name for this task, written as "
            "an imperative verb phrase. Example: 'Submit Student Visa Application'. "
            "Do NOT just copy a raw sentence from the source text."
        )
    )

    description: str = Field(
        description=(
            "1-2 plain-English sentences explaining what the student must "
            "actually do, in your own words (not a direct quote from the source)."
        )
    )

    deadline: Optional[str] = Field(
        default=None,
        description=(
            "The deadline for this task in strict ISO 8601 date format "
            "(YYYY-MM-DD). If the source only gives a relative date "
            "(e.g. 'within 2 weeks of arrival') and no absolute date can be "
            "determined, set this to null - do NOT guess a date."
        ),
    )

    deadline_is_explicit: bool = Field(
        description=(
            "True if the source text stated this deadline directly. "
            "False if you (the AI) inferred it indirectly (e.g. from a "
            "policy rule like 'visas must be filed 90 days before term start')."
        )
    )

    dependencies: List[str] = Field(
        default_factory=list,
        description=(
            "A list of task_name values (from elsewhere in this same tasks "
            "array) that MUST be completed before this task can start. "
            "Infer hidden real-world dependencies even if the source text "
            "never says the word 'dependency' or 'before'."
        ),
    )

    required_documents: List[str] = Field(
        default_factory=list,
        description=(
            "Concrete documents/files the student needs to have ready or "
            "submit for this task. Use an empty list if none are needed."
        ),
    )

    category: Category = Field(
        description="The single best-fitting category bucket for this task."
    )

    priority: Priority = Field(
        description=(
            "HIGH if missing the deadline causes serious consequences "
            "(e.g. loss of visa/enrollment status). MEDIUM for normal "
            "admin tasks. LOW for optional/nice-to-have items."
        )
    )

    source_snippet: Optional[str] = Field(
        default=None,
        description=(
            "A short quote (under 20 words) copied directly from the original "
            "text that this task was extracted from, so a human can verify it."
        ),
    )


class ExtractionResult(BaseModel):
    """The TOP-LEVEL object the AI must return."""

    tasks: List[Task] = Field(
        description="Every distinct task found in the source text, in the order they should logically be tackled."
    )

    extraction_notes: Optional[str] = Field(
        default=None,
        description=(
            "Optional short note about anything ambiguous, missing, or that "
            "a human should double check. Null if nothing to flag."
        ),
    )
