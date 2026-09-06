"""
app/extraction/extractor.py  (AWS Bedrock + Claude version)
==============================================================
Raw text in -> guaranteed-valid ExtractionResult out, via AWS Bedrock.

HOW STRUCTURED OUTPUT WORKS HERE:
Bedrock doesn't have a built-in "response_format=<Pydantic class>" switch.
Instead, we use "forced tool use":
  1. Convert the Pydantic schema into a JSON Schema.
  2. Tell Claude it has one "tool" available called `extract_tasks`, whose
     input must match that JSON Schema.
  3. Force Claude to call that tool (toolChoice), so it must fill in
     structured, schema-shaped arguments instead of writing free text.
  4. Read those arguments back out and validate them into an
     ExtractionResult Python object.
"""

import os
import json
import boto3
from dotenv import load_dotenv

from .schemas import ExtractionResult
from .prompts import SYSTEM_PROMPT

load_dotenv()  # reads your .env file

# ---------------------------------------------------------------------------
# AWS keys (ASIA-prefixed session credentials from the hackathon SSO portal).
# In your .env file:
#     AWS_ACCESS_KEY_ID=ASIA...
#     AWS_SECRET_ACCESS_KEY=...
#     AWS_SESSION_TOKEN=...
#     AWS_REGION=us-east-1
# These expire every 12 hours - re-pull from the access portal if extraction
# suddenly starts failing with an auth error.
# ---------------------------------------------------------------------------
_bedrock = None


def _get_bedrock_client():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client(
            "bedrock-runtime",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            aws_session_token=os.environ.get("AWS_SESSION_TOKEN"),
        )
    return _bedrock


MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0"
)

_EXTRACTION_SCHEMA = ExtractionResult.model_json_schema()

_TOOL_CONFIG = {
    "tools": [
        {
            "toolSpec": {
                "name": "extract_tasks",
                "description": (
                    "Record the tasks, deadlines, dependencies, and required "
                    "documents extracted from the source text."
                ),
                "inputSchema": {"json": _EXTRACTION_SCHEMA},
            }
        }
    ],
    "toolChoice": {"tool": {"name": "extract_tasks"}},
}


def extract_tasks_from_text(raw_text: str) -> ExtractionResult:
    """
    Parameters
    ----------
    raw_text : str
        The messy email body / PDF-extracted text to analyze.

    Returns
    -------
    ExtractionResult
        A validated Python object.
    """

    if not raw_text or not raw_text.strip():
        raise ValueError("raw_text is empty — nothing to extract from.")

    bedrock = _get_bedrock_client()
    response = bedrock.converse(
        modelId=MODEL_ID,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            "Extract all tasks, deadlines, dependencies, and "
                            "required documents from the following source "
                            "text:\n\n---BEGIN SOURCE TEXT---\n"
                            f"{raw_text}\n---END SOURCE TEXT---"
                        )
                    }
                ],
            }
        ],
        toolConfig=_TOOL_CONFIG,
        inferenceConfig={"temperature": 0.2},
    )

    content_blocks = response["output"]["message"]["content"]
    tool_use_block = next(
        (block["toolUse"] for block in content_blocks if "toolUse" in block),
        None,
    )

    if tool_use_block is None:
        raise RuntimeError(
            f"Model did not call the extraction tool as expected. "
            f"Raw response: {json.dumps(response['output'], default=str)}"
        )

    return ExtractionResult.model_validate(tool_use_block["input"])
