from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from .enums import DocumentType


class DocumentSource(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    filename: str
    document_type: DocumentType
    page_number: int | None = None
    source_text: str | None = None
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))