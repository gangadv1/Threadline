# Threadline Backend

FastAPI service that wraps the Member 1 agent workflow (`app/agents`) and
domain models (`app/models`) with a persisted, HTTP API for the frontend.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run the API

```bash
uvicorn app.main:app --reload
```

- Interactive docs: http://127.0.0.1:8000/docs
- OpenAPI schema: http://127.0.0.1:8000/openapi.json

A SQLite file `threadline.db` is created in the working directory on
startup (override the path with the `THREADLINE_DB_PATH` env var).

## Run tests

```bash
pytest
```

This runs the existing 72 agent/model tests (`tests/agents`, `tests/test_models.py`)
unchanged, plus the new API tests (`tests/api`).

## Endpoints

| Method | Path                                          | Purpose |
|--------|-----------------------------------------------|---------|
| GET    | `/health`                                     | Liveness check |
| POST   | `/goals`                                      | Create/persist a goal (e.g. from document extraction) |
| GET    | `/goals`                                      | List goal summaries |
| GET    | `/goals/{goal_id}`                            | Retrieve a full goal |
| PATCH  | `/goals/{goal_id}/tasks/{task_id}`            | Directly correct a task's status/deadline (no replanning) |
| POST   | `/goals/{goal_id}/cycle`                      | Run PLAN → ANALYSE → ACT (`run_agent_cycle`) |
| POST   | `/goals/{goal_id}/disruption`                 | Report a disruption and replan (`run_disruption_cycle`) |
| GET    | `/goals/{goal_id}/actions`                    | List proposed actions for a goal |
| POST   | `/goals/{goal_id}/actions/{action_id}/review` | Approve or reject a proposed action |

All planning/replanning logic lives in `app.agents`; the API layer only
validates requests, loads/saves goal state, and calls
`run_agent_cycle` / `run_disruption_cycle` / `review_action_proposal`.
No endpoint claims to send an email, reminder, or form — approval only
marks a proposal ready for a future send/execute integration.

## Project layout

```
app/
  models/     # domain models (unchanged from Member 1)
  agents/     # planner, replanner, feasibility, actions, orchestrator (unchanged)
  api/
    routers/  # health, goals, cycles, actions
    schemas.py       # request/response wire types (separate from domain models)
    dependencies.py  # get_repository, get_goal_or_404
  database.py # SQLite-backed GoalRepository
  main.py     # FastAPI app, CORS, router wiring
sample_data/
  exchange_application_demo.json  # fixture used by the agent test suite
tests/
  agents/     # existing planner/replanner/feasibility/actions/orchestrator tests
  api/        # new endpoint tests
  test_models.py
```
