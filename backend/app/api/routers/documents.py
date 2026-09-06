from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.dependencies import get_repository
from app.converters import extraction_result_to_goal
from app.database import GoalRepository
from app.extraction.extractor import extract_tasks_from_text
from app.extraction.mock_data import MOCK_EXTRACTION_RESULT
from app.extraction.schemas import ExtractionResult
from app.models import AdministrativeGoal, DocumentSource, DocumentType

router = APIRouter(tags=["documents"])


class ExtractRequest(BaseModel):
    text: str


class CreateGoalFromTextRequest(BaseModel):
    text: str
    title: str
    description: str | None = None
    final_deadline: datetime | None = None
    filename: str = "uploaded-document"
    document_type: DocumentType = DocumentType.OTHER
    use_mock: bool = Field(
        default=False,
        description=(
            "Skip the Bedrock call and use the bundled mock extraction "
            "result instead. Useful for demos or while AWS credentials "
            "aren't set up yet."
        ),
    )


def _run_extraction(text: str, use_mock: bool) -> ExtractionResult:
    if use_mock:
        return MOCK_EXTRACTION_RESULT
    try:
        return extract_tasks_from_text(text)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except Exception as error:  # AWS auth errors, malformed model output, etc.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Extraction failed: {error}",
        ) from error


@router.post("/extract", response_model=ExtractionResult)
def extract(request: ExtractRequest) -> ExtractionResult:
    """Run the AI extractor on raw text and return the structured result
    without creating or persisting a goal."""
    return _run_extraction(request.text, use_mock=False)


@router.post(
    "/goals/from-text",
    response_model=AdministrativeGoal,
    status_code=status.HTTP_201_CREATED,
)
def create_goal_from_text(
    request: CreateGoalFromTextRequest,
    repository: GoalRepository = Depends(get_repository),
) -> AdministrativeGoal:
    """The full pipeline in one call: raw text -> AI extraction ->
    AdministrativeGoal -> persisted.

    Run POST /goals/{id}/cycle afterwards (or call it yourself right after
    this returns) to generate the ordered plan, feasibility report, and
    initial action proposals - this endpoint only extracts and stores.
    """
    extraction = _run_extraction(request.text, use_mock=request.use_mock)
    document = DocumentSource(
        filename=request.filename,
        document_type=request.document_type,
        source_text=request.text,
    )
    goal = extraction_result_to_goal(
        extraction,
        title=request.title,
        description=request.description,
        final_deadline=request.final_deadline,
        document=document,
    )
    return repository.save(goal)
