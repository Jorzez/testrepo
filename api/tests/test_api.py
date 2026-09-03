"""Тесты HTTP-слоя. Neo4j и LLM подменяются, живые сервисы не нужны."""

import pytest
from fastapi.testclient import TestClient

import catalog
import diagnostics
import graph
import main

HEALTHY = {
    "issues": [], "counts": {"error": 0, "warning": 0, "info": 0},
    "check_targets": 3, "ready": True, "problems": [],
}
BROKEN = {
    "issues": [{"code": "targets_without_description", "severity": "error",
                "title": "Атрибуты без описания", "detail": "…",
                "items": [{"label": "проект", "nodeId": "4:db:8", "kind": "CheckTarget"}],
                "fix": None}],
    "counts": {"error": 1, "warning": 0, "info": 0},
    "check_targets": 3, "ready": False,
    "problems": ["Атрибуты без описания: проект"],
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(graph, "verify_connectivity", lambda: True)
    monkeypatch.setattr(graph, "close_driver", lambda: None)
    monkeypatch.setattr(diagnostics, "collect", lambda: HEALTHY)
    with TestClient(main.app) as c:
        yield c


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_ready_ok(client):
    body = client.get("/ready").json()
    assert body["status"] == "ready"
    assert body["problems"] == []


def test_ready_503_on_errors(monkeypatch):
    monkeypatch.setattr(graph, "verify_connectivity", lambda: True)
    monkeypatch.setattr(graph, "close_driver", lambda: None)
    monkeypatch.setattr(diagnostics, "collect", lambda: BROKEN)
    with TestClient(main.app) as c:
        response = c.get("/ready")
    assert response.status_code == 503
    assert "Атрибуты без описания" in response.json()["problems"][0]


def test_ready_503_when_neo4j_down(monkeypatch):
    monkeypatch.setattr(graph, "verify_connectivity", lambda: False)
    monkeypatch.setattr(graph, "close_driver", lambda: None)
    with TestClient(main.app) as c:
        response = c.get("/ready")
    assert response.status_code == 503
    assert response.json()["neo4j"] is False


def test_diagnostics_endpoint(client):
    assert client.get("/catalog/diagnostics").json() == HEALTHY


# ---------------------------- маршруты каталога -----------------------------


def test_tree_passes_archive_flag(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(catalog, "build_tree",
                        lambda inc: seen.setdefault("inc", inc) or {"orders": []})
    client.get("/catalog/tree?include_archived=true")
    assert seen["inc"] is True


def test_node_not_found_maps_to_404(client, monkeypatch):
    def boom(*a, **k):
        raise catalog.NotFound("Узел не найден")

    monkeypatch.setattr(catalog, "get_node", boom)
    response = client.get("/catalog/nodes/4:db:404")
    assert response.status_code == 404
    assert "не найден" in response.json()["detail"]


def test_conflict_maps_to_409(client, monkeypatch):
    def boom(*a, **k):
        raise catalog.Conflict("Удалять можно только архивированный приказ.")

    monkeypatch.setattr(catalog, "delete_node", boom)
    response = client.request("DELETE", "/catalog/nodes/4:db:1")
    assert response.status_code == 409
    assert "архивированный" in response.json()["detail"]


def test_properties_patch_passes_nulls(client, monkeypatch):
    """null должен доезжать до слоя данных: это удаление свойства."""
    seen = {}
    monkeypatch.setattr(catalog, "update_properties",
                        lambda node_id, props: seen.setdefault("props", props) or {"ok": True})
    client.patch("/catalog/nodes/4:db:1/properties",
                 json={"properties": {"подписал": None, "title": "новый"}})
    assert seen["props"] == {"подписал": None, "title": "новый"}


def test_rule_type_is_validated_by_schema(client):
    response = client.post("/catalog/rules", json={
        "clauseNodeId": "4:db:2", "type": "OBLIGATION", "description": "x"})
    assert response.status_code == 422


def test_status_value_is_validated_by_schema(client):
    response = client.post("/catalog/nodes/4:db:1/status", json={"status": "deleted"})
    assert response.status_code == 422


def test_repair_identifiers(client, monkeypatch):
    monkeypatch.setattr(catalog, "repair_identifiers",
                        lambda: {"orders": 1, "clauses": 2, "rules": 0,
                                 "examples": 0, "statuses": 3})
    assert client.post("/catalog/repair-identifiers").json()["clauses"] == 2


def test_check_goal_passes_through(client, monkeypatch):
    monkeypatch.setattr(main, "check_goal",
                        lambda goal: {"goal": goal, "status": "ALLOWED", "allowed": True})
    response = client.post("/check-goal", json={"goal": "цель"})
    assert response.status_code == 200
    assert response.json()["allowed"] is True


def test_check_goal_requires_goal_field(client):
    assert client.post("/check-goal", json={}).status_code == 422
