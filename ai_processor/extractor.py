"""
extractor.py  (AWS Bedrock + Claude version)
==============================================
Same job as before: raw text in -> guaranteed-valid ExtractionResult out.
This version uses AWS Bedrock (running Anthropic's Claude model) instead
of OpenAI or Gemini — this matches what your hackathon's own training
deck recommends, so this is likely your most reliable option.

HOW STRUCTURED OUTPUT WORKS HERE (this part is different from OpenAI/Gemini):
Bedrock doesn't have a built-in "response_format=<Pydantic class>" switch.
Instead, we use a technique called "forced tool use":
  1. We convert your Pydantic schema into a JSON Schema.
  2. We tell Claude it has one "tool" available called `extract_tasks`,
     whose input must match that JSON Schema.
  3. We FORCE Claude to call that tool (toolChoice), so instead of writing
     a text reply, it must fill in structured, schema-shaped arguments.
  4. We read those arguments back out and validate them into your
     ExtractionResult Python object.
This is the standard way to get reliable structured JSON from Claude.
"""

import os
import json
import boto3
from dotenv import load_dotenv

from schemas import ExtractionResult
from prompts import SYSTEM_PROMPT

load_dotenv()  # reads your .env file

# ---------------------------------------------------------------------------
# 1. Set up the Bedrock client using the AWS keys from your hackathon's
#    SSO portal (Access keys page) — the ASIA-prefixed ones with a session
#    token. This matches your hackathon's official setup guide exactly.
#
#    In your .env file, add these 4 lines (exact names matter):
#        AWS_ACCESS_KEY_ID=ASIA...
#        AWS_SECRET_ACCESS_KEY=...
#        AWS_SESSION_TOKEN=...
#        AWS_REGION=us-east-1
#
#    IMPORTANT: these keys expire every 12 hours. If this suddenly stops
#    working after it worked before, re-login to the AWS access portal,
#    grab fresh keys from "Access keys", and update your .env.
# ---------------------------------------------------------------------------
bedrock = boto3.client(
    "bedrock-runtime",
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    aws_session_token=os.environ.get("AWS_SESSION_TOKEN"),
)

# This exact model ID is confirmed straight from your hackathon's own
# official training slide — no guessing needed.
MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0"
)

# Build the JSON Schema Claude must fill in, directly from your Pydantic class.
# You never have to hand-write or maintain this — it's auto-generated.
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
    # Forcing this specific tool means Claude MUST respond with structured
    # arguments matching the schema, instead of a free-text reply.
    "toolChoice": {"tool": {"name": "extract_tasks"}},
}


def extract_tasks_from_text(raw_text: str) -> ExtractionResult:
    """
    The one function Role 3 (Backend) needs to call.

    Parameters
    ----------
    raw_text : str
        The messy email body / PDF-extracted text you want analyzed.

    Returns
    -------
    ExtractionResult
        A validated Python object. Access fields like:
            result.tasks[0].task_name
            result.tasks[0].deadline
        For a plain dict/JSON, call `.model_dump()` or `.model_dump_json()`.
    """

    if not raw_text or not raw_text.strip():
        raise ValueError("raw_text is empty — nothing to extract from.")

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
        inferenceConfig={"temperature": 0.2},  # low = more consistent output
    )

    # Dig through the response to find the tool call Claude made.
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

    # tool_use_block["input"] is already a plain Python dict — validate it
    # against your schema. If Claude ever produces a slightly malformed
    # shape, this line will raise a clear Pydantic validation error instead
    # of silently passing bad data downstream.
    return ExtractionResult.model_validate(tool_use_block["input"])


# ---------------------------------------------------------------------------
# Quick manual test — run `python3 extractor.py` directly to try it out.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sample_email = """
    Subject: Important - Student Pass & Housing Steps

    Dear Student,

    Please note that all incoming exchange students must apply for their
    Student's Pass through ICA within 2 weeks of receiving their In-Principle
    Approval (IPA) letter. You will need a valid passport and one recent
    passport photo.

    Separately, hostel move-in requires your housing deposit of $500 to be
    paid by 15 August 2026. Rooms are only released after payment clears.

    Course bidding opens after your matriculation is confirmed, which itself
    only happens once tuition fees are settled.
    """

    result = extract_tasks_from_text(sample_email)
    print(result.model_dump_json(indent=2))
