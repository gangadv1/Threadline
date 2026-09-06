from __future__ import annotations

from fastapi.testclient import TestClient

AS_OF = "2026-09-01T09:00:00Z"


def _goal_payload(goal_id: str = "goal-1") -> dict:
    return {
        "id": goal_id,
        "title": "Submit financial aid form",
        "description": "Complete the financial aid renewal.",
        "final_deadline": "2026-10-01T00:00:00Z",
        "tasks": [
            {
                "id": "task-a",
                "title": "Gather income documents",
                "description": "Collect pay stubs and tax forms.",
                "estimated_processing_time_days": 2,
            },
            {
                "id": "task-b",
                "title": "Submit form",
                "description": "Submit the completed form online.",
                "estimated_processing_time_days": 1,
                "dependencies": [
                    {"prerequisite_task_id": "task-a", "reason": "Form needs the documents."}
                ],
            },
        ],
    }


def test_health_check(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_list_and_get_goal(client: TestClient) -> None:
    create_response = client.post("/goals", json=_goal_payload())
    assert create_response.status_code == 201

    list_response = client.get("/goals")
    assert list_response.status_code == 200
    summaries = list_response.json()
    assert len(summaries) == 1
    assert summaries[0]["task_count"] == 2

    get_response = client.get("/goals/goal-1")
    assert get_response.status_code == 200
    assert get_response.json()["title"] == "Submit financial aid form"


def test_creating_duplicate_goal_conflicts(client: TestClient) -> None:
    client.post("/goals", json=_goal_payload())

    response = client.post("/goals", json=_goal_payload())

    assert response.status_code == 409


def test_unknown_goal_returns_404(client: TestClient) -> None:
    response = client.get("/goals/does-not-exist")

    assert response.status_code == 404


def test_run_cycle_returns_plan_and_actions(client: TestClient) -> None:
    client.post("/goals", json=_goal_payload())

    response = client.post(
        "/goals/goal-1/cycle", json={"as_of": AS_OF, "max_proposals": 5}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ordered_task_ids"] == ["task-a", "task-b"]
    assert body["recommended_next_task_id"] == "task-a"
    assert body["updated_goal"]["proposed_actions"]

    persisted = client.get("/goals/goal-1").json()
    assert persisted["next_action_summary"] is not None


def test_disruption_endpoint_blocks_downstream_tasks(client: TestClient) -> None:
    client.post("/goals", json=_goal_payload())

    response = client.post(
        "/goals/goal-1/disruption",
        json={
            "task_id": "task-a",
            "new_status": "rejected",
            "as_of": AS_OF,
            "reason": "Documents were rejected as incomplete.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    statuses = {task["id"]: task["status"] for task in body["updated_goal"]["tasks"]}
    assert statuses["task-a"] == "rejected"
    assert statuses["task-b"] == "blocked"
    assert "Documents were rejected" in body["disruption_summary"]


def test_disruption_on_unknown_task_returns_404(client: TestClient) -> None:
    client.post("/goals", json=_goal_payload())

    response = client.post(
        "/goals/goal-1/disruption",
        json={"task_id": "missing", "new_status": "blocked", "as_of": AS_OF},
    )

    assert response.status_code == 404


def test_goal_deadline_can_be_updated_directly(client: TestClient) -> None:
    client.post("/goals", json=_goal_payload())

    response = client.patch(
        "/goals/goal-1", json={"final_deadline": "2026-09-15T00:00:00Z"}
    )

    assert response.status_code == 200
    assert response.json()["final_deadline"] == "2026-09-15T00:00:00+00:00"


def test_goal_update_requires_a_field(client: TestClient) -> None:
    client.post("/goals", json=_goal_payload())

    response = client.patch("/goals/goal-1", json={})

    assert response.status_code == 400


def test_goal_deadline_can_be_updated_directly(client: TestClient) -> None:
    client.post("/goals", json=_goal_payload())

    response = client.patch(
        "/goals/goal-1", json={"final_deadline": "2026-09-20T00:00:00Z"}
    )

    assert response.status_code == 200
    assert response.json()["final_deadline"] == "2026-09-20T00:00:00Z"


def test_goal_update_requires_a_field(client: TestClient) -> None:
    client.post("/goals", json=_goal_payload())

    response = client.patch("/goals/goal-1", json={})

    assert response.status_code == 400


def test_updating_unknown_goal_returns_404(client: TestClient) -> None:
    response = client.patch(
        "/goals/does-not-exist", json={"title": "New title"}
    )

    assert response.status_code == 404


def test_task_status_can_be_updated_directly(client: TestClient) -> None:
    client.post("/goals", json=_goal_payload())

    response = client.patch(
        "/goals/goal-1/tasks/task-a", json={"status": "in_progress"}
    )

    assert response.status_code == 200
    task = next(t for t in response.json()["tasks"] if t["id"] == "task-a")
    assert task["status"] == "in_progress"


def test_task_status_update_requires_a_field(client: TestClient) -> None:
    client.post("/goals", json=_goal_payload())

    response = client.patch("/goals/goal-1/tasks/task-a", json={})

    assert response.status_code == 400


def test_updating_unknown_task_returns_404(client: TestClient) -> None:
    client.post("/goals", json=_goal_payload())

    response = client.patch(
        "/goals/goal-1/tasks/does-not-exist", json={"status": "blocked"}
    )

    assert response.status_code == 404


def test_action_can_be_approved_and_edited(client: TestClient) -> None:
    client.post("/goals", json=_goal_payload())
    client.post("/goals/goal-1/cycle", json={"as_of": AS_OF, "max_proposals": 5})

    actions = client.get("/goals/goal-1/actions").json()
    assert actions
    action_id = actions[0]["id"]

    response = client.post(
        f"/goals/goal-1/actions/{action_id}/review",
        json={"decision": "approved", "edited_content": "Edited reminder text"},
    )

    assert response.status_code == 200
    reviewed = next(
        item for item in response.json()["proposed_actions"] if item["id"] == action_id
    )
    assert reviewed["approval_status"] == "approved"


def test_reviewing_unknown_action_returns_404(client: TestClient) -> None:
    client.post("/goals", json=_goal_payload())

    response = client.post(
        "/goals/goal-1/actions/does-not-exist/review",
        json={"decision": "approved"},
    )

    assert response.status_code == 404


def test_docs_endpoints_are_available(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200
