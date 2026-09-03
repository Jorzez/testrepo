"""Тесты HTTP-слоя. Neo4j и LLM подменяются, живые сервисы не нужны."""

import pytest
from fastapi.testclient import TestClient

import graph
import main

TARGETS = [{"name": "проект", "description": "назван проект"}]

CLEAN_DIAGNOSTICS = {
    "duplicate_check_targets": [],
    "check_targets_without_description": [],
    "orphan_check_targets": [],
    "rules_without_target": [],
    "problems": [],
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(graph, "verify_connectivity", lambda: True)
    monkeypatch.setattr(graph, "close_driver", lambda: None)
    monkeypatch.setattr(graph, "get_check_targets", lambda: TARGETS)
    monkeypatch.setattr(graph, "diagnose", lambda: dict(CLEAN_DIAGNOSTICS))
    with TestClient(main.app) as c:
        yield c


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_ready_ok(client):
    body = client.get("/ready").json()
    assert body["status"] == "ready"
    assert body["check_targets"] == 1
    assert body["problems"] == []


def test_ready_503_when_graph_empty(monkeypatch):
    monkeypatch.setattr(graph, "verify_connectivity", lambda: True)
    monkeypatch.setattr(graph, "close_driver", lambda: None)
    monkeypatch.setattr(graph, "get_check_targets", list)
    monkeypatch.setattr(graph, "diagnose", lambda: dict(CLEAN_DIAGNOSTICS))
    with TestClient(main.app) as c:
        response = c.get("/ready")
    assert response.status_code == 503
    assert "пуст" in response.json()["problems"][0]


def test_ready_503_on_duplicate_check_targets(monkeypatch):
    """Двойники атрибутов делают проверку молча неполной — это не готовность."""
    diagnostics = dict(CLEAN_DIAGNOSTICS)
    diagnostics["problems"] = ['Дубликаты атрибута: "срок исполнения", "срок_исполнения"']
    monkeypatch.setattr(graph, "verify_connectivity", lambda: True)
    monkeypatch.setattr(graph, "close_driver", lambda: None)
    monkeypatch.setattr(graph, "get_check_targets", lambda: TARGETS)
    monkeypatch.setattr(graph, "diagnose", lambda: diagnostics)
    with TestClient(main.app) as c:
        response = c.get("/ready")
    assert response.status_code == 503
    assert "Дубликаты" in response.json()["problems"][0]


def test_ready_503_when_neo4j_down(monkeypatch):
    monkeypatch.setattr(graph, "verify_connectivity", lambda: False)
    monkeypatch.setattr(graph, "close_driver", lambda: None)
    with TestClient(main.app) as c:
        response = c.get("/ready")
    assert response.status_code == 503
    assert response.json()["neo4j"] is False


def test_check_targets_endpoint(client):
    assert client.get("/check-targets").json() == {"targets": TARGETS}


def test_check_goal_passes_through(client, monkeypatch):
    monkeypatch.setattr(
        main, "check_goal", lambda goal: {"goal": goal, "status": "ALLOWED", "allowed": True}
    )
    response = client.post("/check-goal", json={"goal": "цель"})
    assert response.status_code == 200
    assert response.json()["allowed"] is True


def test_check_goal_requires_goal_field(client):
    assert client.post("/check-goal", json={}).status_code == 422
