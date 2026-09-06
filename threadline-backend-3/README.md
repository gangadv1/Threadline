# Threadline Backend

FastAPI service that turns extracted tasks into a planned, feasibility-checked,
disruption-aware `AdministrativeGoal`, and serves it to the frontend.

```
Documents -> AI extraction (app/extraction) -> AdministrativeGoal (app/converters)
    -> API (app/api) -> agent workflow (app/agents) -> SQLite (app/database)
    -> results -> frontend (index.html)
```

## Run it

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env        # fill in AWS Bedrock keys if you want real extraction
uvicorn app.main:app --reload --port 8000
```

Open `http://127.0.0.1:8000/docs` for the interactive API explorer.

Then open the frontend (`frontend/index.html`) directly in a browser, or serve it
with `python3 -m http.server 5500` — either way it will detect the backend at
`http://127.0.0.1:8000` and switch its badge from "○ Demo data" to "● Live backend".

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check |
| POST | `/goals` | Persist a fully-formed `AdministrativeGoal` (e.g. the frontend's seed goal) |
| GET | `/goals` | List goal summaries |
| GET | `/goals/{id}` | Fetch a goal |
| PATCH | `/goals/{id}` | Directly correct goal-level fields (title, deadline, status) |
| PATCH | `/goals/{id}/tasks/{task_id}` | Directly correct a task's status/deadline, no replanning |
| POST | `/goals/{id}/cycle` | Run PLAN → ANALYSE → ACT, persist and return the result |
| POST | `/goals/{id}/disruption` | Apply a task disruption (reject/block/reschedule), replan, persist |
| POST | `/goals/{id}/actions/{action_id}/review` | Approve/reject a proposed action (nothing is ever auto-sent) |
| POST | `/extract` | Run the AI extractor on raw text, return the structured result (no persistence) |
| POST | `/goals/from-text` | Full pipeline: raw text → extraction → `AdministrativeGoal` → persisted |

`/goals/from-text` accepts `"use_mock": true` to skip the Bedrock call and use the
bundled sample extraction (`app/extraction/mock_data.py`) — useful before AWS
credentials are set up, or for a reliable demo.

## Persistence

SQLite, one row per goal, storing the full `AdministrativeGoal` as JSON
(`app/database.py`). The Pydantic model is the single source of truth for
shape/validation, so there's no separate relational schema to keep in sync.
Set `THREADLINE_DB_PATH` to change the file location (defaults to
`threadline.db` in the working directory).

## Tests

```bash
pytest
```

`tests/test_api.py` exercises the full lifecycle through the HTTP layer: create
a goal, run a cycle, trigger a disruption and check downstream blocking,
update a task directly, review a proposed action, and create a goal from mock
extraction text.

## Layout

```
app/
  models/       AdministrativeGoal, AdministrativeTask, Risk, ActionProposal, ... (Pydantic, domain layer)
  agents/       planner, replanner, feasibility, actions, orchestrator (PLAN/ANALYSE/ACT/ADAPT)
  extraction/   Bedrock+Claude extractor, prompts, extraction-only schemas, mock data
  converters.py ExtractionResult -> AdministrativeGoal
  database.py   SQLite persistence (goal-as-JSON)
  api/
    schemas.py       API-only request/response shapes
    dependencies.py  shared FastAPI dependencies (repository, 404 lookup)
    routers/         health, goals, cycles, actions, documents
  main.py       FastAPI app, CORS, router registration
```
