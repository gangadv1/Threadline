from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("THREADLINE_DB_PATH", str(db_path))

    # database.py reads THREADLINE_DB_PATH at import time, so make sure we
    # get a fresh module (and a fresh app) bound to this test's db path.
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            del sys.modules[module_name]

    main = importlib.import_module("app.main")
    with TestClient(main.app) as test_client:
        yield test_client


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sample_goal() -> dict:
    return {
        "id": "goal-test-1",
        "title": "Submit exchange application",
        "description": "Test goal",
        "final_deadline": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        "tasks": [
            {
                "id": "task-a",
                "title": "Confirm eligibility",
                "description": "Check eligibility",
                "priority": "high",
                "estimated_processing_time_days": 1,
                "dependencies": [],
            },
            {
                "id": "task-b",
                "title": "Request transcript",
                "description": "Request official transcript",
                "priority": "urgent",
                "estimated_processing_time_days": 5,
                "dependencies": [
                    {"prerequisite_task_id": "task-a", "reason": "Eligibility must be confirmed first."}
                ],
            },
        ],
    }


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_and_get_goal(client):
    payload = _sample_goal()
    created = client.post("/goals", json=payload)
    assert created.status_code == 201
    assert created.json()["id"] == "goal-test-1"

    fetched = client.get("/goals/goal-test-1")
    assert fetched.status_code == 200
    assert len(fetched.json()["tasks"]) == 2


def test_duplicate_goal_conflicts(client):
    payload = _sample_goal()
    client.post("/goals", json=payload)
    duplicate = client.post("/goals", json=payload)
    assert duplicate.status_code == 409


def test_run_cycle_orders_tasks_and_sets_next_action(client):
    client.post("/goals", json=_sample_goal())
    result = client.post(
        "/goals/goal-test-1/cycle",
        json={"as_of": _now_iso(), "max_proposals": 5},
    )
    assert result.status_code == 200
    body = result.json()
    assert body["ordered_task_ids"] == ["task-a", "task-b"]
    assert body["recommended_next_task_id"] == "task-a"
    assert body["updated_goal"]["next_action_summary"]
    assert "feasibility_report" in body


def test_disruption_blocks_downstream_tasks(client):
    client.post("/goals", json=_sample_goal())
    client.post("/goals/goal-test-1/cycle", json={"as_of": _now_iso()})

    result = client.post(
        "/goals/goal-test-1/disruption",
        json={
            "task_id": "task-a",
            "new_status": "rejected",
            "as_of": _now_iso(),
            "reason": "Ineligible for exchange this term.",
        },
    )
    assert result.status_code == 200
    tasks_by_id = {t["id"]: t for t in result.json()["updated_goal"]["tasks"]}
    assert tasks_by_id["task-a"]["status"] == "rejected"
    assert tasks_by_id["task-b"]["status"] == "blocked"


def test_update_task_status_directly(client):
    client.post("/goals", json=_sample_goal())
    result = client.patch(
        "/goals/goal-test-1/tasks/task-a", json={"status": "completed"}
    )
    assert result.status_code == 200
    tasks_by_id = {t["id"]: t for t in result.json()["tasks"]}
    assert tasks_by_id["task-a"]["status"] == "completed"


def test_review_action_proposal(client):
    client.post("/goals", json=_sample_goal())
    cycle = client.post("/goals/goal-test-1/cycle", json={"as_of": _now_iso()})
    proposals = cycle.json()["updated_goal"]["proposed_actions"]
    assert proposals, "expected at least one proposed action after a cycle"
    action_id = proposals[0]["id"]

    review = client.post(
        f"/goals/goal-test-1/actions/{action_id}/review",
        json={"decision": "approved"},
    )
    assert review.status_code == 200
    updated_proposals = {a["id"]: a for a in review.json()["proposed_actions"]}
    assert updated_proposals[action_id]["approval_status"] == "approved"


def test_goal_from_text_uses_mock_extraction(client):
    result = client.post(
        "/goals/from-text",
        json={
            "text": "Please request your transcript within 2 weeks.",
            "title": "Exchange application (mock)",
            "use_mock": True,
        },
    )
    assert result.status_code == 201
    body = result.json()
    assert len(body["tasks"]) == 5
    titles = {task["title"] for task in body["tasks"]}
    assert "Apply for Student's Pass" in titles


def test_goal_not_found_returns_404(client):
    response = client.get("/goals/does-not-exist")
    assert response.status_code == 404
