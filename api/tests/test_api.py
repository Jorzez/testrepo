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
    monkeypatch.setattr(main, "check_goal", lambda goal, department_id=None: {
        "goal": goal, "status": "ALLOWED", "allowed": True, "seen_department": department_id})
    response = client.post("/check-goal", json={"goal": "цель"})
    assert response.status_code == 200
    assert response.json()["allowed"] is True
    assert response.json()["seen_department"] is None, "в одиночной проверке подразделение необязательно"


def test_check_goal_passes_department(client, monkeypatch):
    monkeypatch.setattr(main, "check_goal",
                        lambda goal, department_id=None: {"seen_department": department_id})
    response = client.post("/check-goal", json={"goal": "цель", "department_id": "UCT"})
    assert response.json()["seen_department"] == "UCT"


def test_check_goal_requires_goal_field(client):
    assert client.post("/check-goal", json={}).status_code == 422


# --------------------------- пакетная проверка ------------------------------


def test_check_goals_accepts_array(client, monkeypatch):
    monkeypatch.setattr(main, "check_goals", lambda items: {
        "results": [{"id": i["id"], "goal": i["goal"], "status": "ALLOWED", "allowed": True}
                    for i in items],
        "summary": {"total": len(items), "allowed": len(items),
                    "violations": 0, "manual_review": 0},
    })
    response = client.post("/check-goals", json=[
        {"goal": "первая", "id": "g-1", "department_id": "UCT"},
        {"goal": "вторая", "id": "g-2", "department_id": "AGD"}])
    assert response.status_code == 200
    assert [r["id"] for r in response.json()["results"]] == ["g-1", "g-2"]
    assert response.json()["summary"]["total"] == 2


def test_check_goals_id_is_optional(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(main, "check_goals",
                        lambda items: seen.setdefault("items", items) or {"results": [], "summary": {}})
    client.post("/check-goals", json=[{"goal": "без id", "department_id": "UCT"}])
    assert seen["items"] == [{"goal": "без id", "department_id": "UCT", "id": None}]


@pytest.mark.parametrize("item", [{"goal": "цель"}, {"goal": "цель", "department_id": ""}])
def test_check_goals_requires_department(client, item):
    """В пакете подразделение обязательно: кадровая система его знает."""
    response = client.post("/check-goals", json=[item])
    assert response.status_code == 422
    assert "department_id" in response.text


def test_check_goals_rejects_empty_goal(client):
    response = client.post("/check-goals", json=[{"goal": "", "id": "x", "department_id": "UCT"}])
    assert response.status_code == 422


def test_check_goals_rejects_oversized_batch(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_BATCH", 2)
    response = client.post("/check-goals", json=[{"goal": f"ц{i}", "department_id": "UCT"} for i in range(3)])
    assert response.status_code == 413
    assert "не более 2" in response.json()["detail"]


def test_delete_passes_force_flag(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(catalog, "delete_node",
                        lambda node_id, cascade, force: seen.setdefault("force", force) or {"deleted": node_id})
    client.request("DELETE", "/catalog/nodes/4:db:2?force=true")
    assert seen["force"] is True


def test_delete_without_force_defaults_to_false(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(catalog, "delete_node",
                        lambda node_id, cascade, force: seen.setdefault("force", force) or {"deleted": node_id})
    client.request("DELETE", "/catalog/nodes/4:db:2")
    assert seen["force"] is False


# ------------------------------ подразделения -------------------------------


def test_departments_list(client, monkeypatch):
    monkeypatch.setattr(catalog, "list_departments", lambda include_archived: [
        {"nodeId": "4:db:9", "departmentId": "UCT", "name": "УЦТ"}])
    assert client.get("/catalog/departments").json()["departments"][0]["departmentId"] == "UCT"


def test_create_department_conflict_is_409(client, monkeypatch):
    def clash(department_id, name):
        raise catalog.Conflict("уже существует")

    monkeypatch.setattr(catalog, "create_department", clash)
    response = client.post("/catalog/departments", json={"departmentId": "UCT", "name": "УЦТ"})
    assert response.status_code == 409


def test_create_department_requires_id_and_name(client):
    assert client.post("/catalog/departments", json={"name": "УЦТ"}).status_code == 422
    assert client.post("/catalog/departments", json={"departmentId": "UCT", "name": ""}).status_code == 422


def test_rule_scope_passes_through(client, monkeypatch):
    seen = {}

    def scope(node_id, only, exceptions):
        seen.update(node_id=node_id, only=only, exceptions=exceptions)
        return {"only": only, "exceptions": exceptions}

    monkeypatch.setattr(catalog, "set_rule_scope", scope)
    response = client.put("/catalog/rules/4:db:3/departments", json={
        "only": ["UCT"], "exceptions": [{"departmentId": "FIN", "basis": "4.2", "status": "active"}]})
    assert response.status_code == 200
    assert seen["only"] == ["UCT"]
    assert seen["exceptions"] == [
        {"departmentId": "FIN", "status": "active", "basis": "4.2", "note": None}]


def test_rule_scope_exception_defaults_to_candidate(client, monkeypatch):
    """Исключение без явного статуса — кандидат: в вердикте не участвует."""
    seen = {}
    monkeypatch.setattr(catalog, "set_rule_scope",
                        lambda node_id, only, exceptions: seen.setdefault("e", exceptions) and {})
    client.put("/catalog/rules/4:db:3/departments", json={"exceptions": [{"departmentId": "FIN"}]})
    assert seen["e"][0]["status"] == "candidate"


def test_rule_scope_rejects_unknown_exception_status(client):
    response = client.put("/catalog/rules/4:db:3/departments",
                          json={"exceptions": [{"departmentId": "FIN", "status": "approved"}]})
    assert response.status_code == 422
