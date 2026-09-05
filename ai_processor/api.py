"""
api.py
======
A minimal FastAPI app exposing your extraction logic as an HTTP endpoint,
so Role 3 (Backend) and Role 4 (Frontend) can call it without knowing any
Python or OpenAI details — they just POST text and get JSON back.

Run it with:
    uvicorn api:app --reload --port 8000

Then test it in your browser at:
    http://127.0.0.1:8000/docs
    (FastAPI auto-generates an interactive test page here — huge time-saver)
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from schemas import ExtractionResult
from extractor import extract_tasks_from_text

app = FastAPI(title="Threadline - AI Task Extraction Service")


class ExtractRequest(BaseModel):
    """What the frontend/backend sends us: just the raw text."""
    text: str


@app.post("/extract", response_model=ExtractionResult)
def extract(request: ExtractRequest) -> ExtractionResult:
    """
    POST /extract
    Body:  { "text": "...raw email or PDF-extracted text..." }
    Returns: an ExtractionResult JSON object (see schemas.py)
    """
    try:
        return extract_tasks_from_text(request.text)
    except ValueError as e:
        # Bad input from the caller (e.g. empty text)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # Anything else (API key missing, OpenAI error, etc.)
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")


@app.get("/health")
def health():
    """Simple endpoint so teammates can check the service is running."""
    return {"status": "ok"}
