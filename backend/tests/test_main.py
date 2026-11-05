from collections.abc import AsyncIterator
from copy import deepcopy
import json

import pytest
from fastapi.testclient import TestClient

from app import main


client = TestClient(main.app)
initial_visits = deepcopy(main.VISITS)
initial_tasks = deepcopy(main.TASKS)
initial_schedule_order = list(main.SCHEDULE_ORDER)


@pytest.fixture(autouse=True)
def reset_demo_state():
    main.VISITS.clear()
    main.VISITS.update(deepcopy(initial_visits))
    main.TASKS.clear()
    main.TASKS.update(deepcopy(initial_tasks))
    main.SCHEDULE_ORDER[:] = initial_schedule_order
    main.APPROVED_DRAFTS.clear()


class FakeUpdate:
    def __init__(self, text: str):
        self.text = text


class FakeAgent:
    def __init__(self, output: dict):
        self.output = json.dumps(output, ensure_ascii=False)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def run_stream(self, prompt: str) -> AsyncIterator[FakeUpdate]:
        midpoint = len(self.output) // 2
        yield FakeUpdate(self.output[:midpoint])
        yield FakeUpdate(self.output[midpoint:])


def consent_all(visit_id: str) -> None:
    client.put(
        f"/api/v1/visits/{visit_id}/participants-confirmation",
        json={"confirmed": True},
    )
    visit = main.VISITS[visit_id]
    for person in visit.participants:
        client.put(
            f"/api/v1/visits/{visit_id}/participants/{person.id}/consent",
            json={"consent": "consented"},
        )


def test_dashboard_contains_synthetic_visits_and_tasks():
    response = client.get("/api/v1/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert data["synthetic_data_only"] is True
    assert len(data["visits"]) == 2
    assert all("transcript" not in visit for visit in data["visits"])
    assert data["open_tasks"]


def test_home_serves_the_dashboard_ui():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "다녀왔어요" in response.text
    assert "합성 데이터 데모" in response.text
    assert "moveVisit" in response.text
    assert "createTask" in response.text
    assert "case-profile" in response.text


def test_recording_is_blocked_until_all_participants_confirmed():
    response = client.post("/api/v1/visits/visit-001/recording/start")
    assert response.status_code == 409


def test_participant_consent_gates_start_and_resume():
    consent_all("visit-001")
    started = client.post("/api/v1/visits/visit-001/recording/start")
    assert started.status_code == 200
    assert started.json()["status"] == "recording"
    assert started.json()["participants_confirmed_at"]
    assert all(person["consent_at"] for person in started.json()["participants"])

    response = client.post("/api/v1/visits/visit-001/recording/pause")
    assert response.status_code == 200
    participant_id = main.VISITS["visit-001"].participants[0].id
    client.put(
        f"/api/v1/visits/visit-001/participants/{participant_id}/consent",
        json={"consent": "declined"},
    )
    blocked = client.post("/api/v1/visits/visit-001/recording/resume")
    assert blocked.status_code == 409


def test_adding_participant_resets_confirmation_and_pauses_recording():
    consent_all("visit-001")
    client.post("/api/v1/visits/visit-001/recording/start")
    response = client.post(
        "/api/v1/visits/visit-001/participants",
        json={"label": "합성 방문자", "role": "대화 참여자"},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "paused"
    assert response.json()["consent_ready"] is False
    assert response.json()["participants_confirmed"] is False
    assert response.json()["participants_confirmed_at"] is None


def test_schedule_reorder_requires_exact_visit_ids():
    response = client.put(
        "/api/v1/schedule/order",
        json={"visit_ids": ["visit-002", "visit-001"]},
    )
    assert response.status_code == 200
    assert [visit["id"] for visit in response.json()["visits"]] == [
        "visit-002",
        "visit-001",
    ]
    invalid = client.put("/api/v1/schedule/order", json={"visit_ids": ["visit-001"]})
    assert invalid.status_code == 422


def test_task_creation_and_completion_updates_dashboard():
    created = client.post(
        "/api/v1/tasks",
        json={
            "case_id": "case-001",
            "title": "합성 후속 업무",
            "priority": "high",
        },
    )
    assert created.status_code == 201
    task_id = created.json()["id"]
    done = client.put(f"/api/v1/tasks/{task_id}", json={"status": "done"})
    assert done.status_code == 200
    assert done.json()["status"] == "done"


def test_azure_demo_rejects_free_text_participants_and_tasks(monkeypatch):
    monkeypatch.setenv("WEBSITE_INSTANCE_ID", "test-instance")
    participant = client.post(
        "/api/v1/visits/visit-001/participants",
        json={"label": "Real person's name", "role": "대화 참여자"},
    )
    task = client.post(
        "/api/v1/tasks",
        json={
            "case_id": "case-001",
            "title": "Arbitrary personal details",
        },
    )
    assert participant.status_code == 422
    assert task.status_code == 422


def test_draft_endpoint_reports_missing_model_runtime(monkeypatch):
    monkeypatch.setattr(main, "configured_copilot_cli", lambda: None)
    consent_all("visit-002")
    client.post("/api/v1/visits/visit-002/recording/start")
    client.post("/api/v1/visits/visit-002/recording/stop")
    response = client.post(
        "/api/v1/visits/draft",
        json={"visit_id": "visit-002"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "COPILOT_CLI_NOT_FOUND"


def test_draft_request_rejects_caller_supplied_transcript():
    consent_all("visit-001")
    client.post("/api/v1/visits/visit-001/recording/start")
    client.post("/api/v1/visits/visit-001/recording/stop")

    response = client.post(
        "/api/v1/visits/draft",
        json={"visit_id": "visit-001", "transcript": "arbitrary text"},
    )

    assert response.status_code == 422


def test_transcript_is_visible_only_after_recording_stops():
    before_stop = client.get("/api/v1/visits/visit-001/transcript")
    assert before_stop.status_code == 409
    consent_all("visit-001")
    client.post("/api/v1/visits/visit-001/recording/start")
    client.post("/api/v1/visits/visit-001/recording/stop")

    response = client.get("/api/v1/visits/visit-001/transcript")

    assert response.status_code == 200
    assert response.json()["synthetic"] is True
    assert response.json()["text"] == main.VISITS["visit-001"].transcript


def test_draft_endpoint_streams_only_verified_evidence(monkeypatch):
    evidence = "요즘 입맛이 없고 아침은 자주 거릅니다."
    output = {
        "items": [
            {
                "category": "food",
                "content": "아침 식사를 자주 거름",
                "evidence": evidence,
                "needs_review": False,
            }
        ],
        "welfare_candidates": [],
        "follow_up_actions": [],
    }
    monkeypatch.setattr(main, "configured_copilot_cli", lambda: "copilot")
    monkeypatch.setattr(main, "build_agent", lambda _: FakeAgent(output))
    consent_all("visit-001")
    client.post("/api/v1/visits/visit-001/recording/start")
    client.post("/api/v1/visits/visit-001/recording/stop")

    response = client.post(
        "/api/v1/visits/draft",
        json={"visit_id": "visit-001"},
    )

    assert response.status_code == 200
    assert "event: delta" in response.text
    assert '"unverified":true' in response.text
    assert "event: draft" in response.text
    assert "needs_human_review" in response.text


def test_draft_endpoint_rejects_unverifiable_evidence(monkeypatch):
    output = {
        "items": [
            {
                "category": "health_condition",
                "content": "임의로 생성된 건강 정보",
                "evidence": "원문에 없는 발언",
                "needs_review": False,
            }
        ],
        "welfare_candidates": [],
        "follow_up_actions": [],
    }
    monkeypatch.setattr(main, "configured_copilot_cli", lambda: "copilot")
    monkeypatch.setattr(main, "build_agent", lambda _: FakeAgent(output))
    consent_all("visit-001")
    client.post("/api/v1/visits/visit-001/recording/start")
    client.post("/api/v1/visits/visit-001/recording/stop")

    response = client.post(
        "/api/v1/visits/draft",
        json={"visit_id": "visit-001"},
    )

    assert response.status_code == 200
    assert "DRAFT_VALIDATION_FAILED" in response.text
    assert "event: draft" not in response.text


def test_approval_rejects_nonmatching_evidence():
    consent_all("visit-001")
    client.post("/api/v1/visits/visit-001/recording/start")
    client.post("/api/v1/visits/visit-001/recording/stop")
    response = client.post(
        "/api/v1/visits/visit-001/drafts/draft-test/approve",
        json={
            "items": [
                {
                    "category": "health_condition",
                    "content": "임의로 만든 내용",
                    "evidence": "전사에 없는 내용",
                    "needs_review": False,
                }
            ],
            "welfare_candidates": [],
            "follow_up_actions": [],
        },
    )
    assert response.status_code == 422


def test_azure_demo_rejects_free_text_approval(monkeypatch):
    monkeypatch.setenv("WEBSITE_INSTANCE_ID", "test-instance")
    consent_all("visit-001")
    client.post("/api/v1/visits/visit-001/recording/start")
    client.post("/api/v1/visits/visit-001/recording/stop")
    response = client.post(
        "/api/v1/visits/visit-001/drafts/draft-test/approve",
        json={
            "items": [
                {
                    "category": "health_condition",
                    "content": "Arbitrary personal details",
                    "evidence": "합성 어르신: 요즘 입맛이 없고 아침은 자주 거릅니다.",
                    "needs_review": False,
                }
            ],
            "welfare_candidates": [],
            "follow_up_actions": [],
        },
    )
    assert response.status_code == 422
