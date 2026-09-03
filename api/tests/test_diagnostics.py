"""Тесты диагностики: находит ли она то, что уже ломало проверки."""

import pytest

import diagnostics

TARGET_A = "4:db:7"
TARGET_B = "4:db:8"
RULE = "4:db:3"
ORDER = "4:db:1"


@pytest.fixture
def db(monkeypatch):
    rows: dict[str, list[dict]] = {}
    monkeypatch.setattr(diagnostics, "_run", lambda q, **p: rows.get(q, []))
    return type("DB", (), {"rows": rows})


def _healthy(db):
    db.rows[diagnostics.Q_TARGETS] = [
        {"nodeId": TARGET_A, "name": "проект", "description": "назван проект", "status": "active"}
    ]
    db.rows[diagnostics.Q_TARGET_USAGE] = [{"name": "проект", "rule_count": 1}]
    return db


def codes(report):
    return [issue["code"] for issue in report["issues"]]


def test_healthy_graph_is_ready(db):
    _healthy(db)
    report = diagnostics.collect()
    assert report["ready"] is True
    assert report["counts"]["error"] == 0
    assert report["problems"] == []


def test_empty_dictionary_is_an_error(db):
    report = diagnostics.collect()
    assert "no_check_targets" in codes(report)
    assert report["ready"] is False


def test_finds_targets_without_description(db):
    _healthy(db)
    db.rows[diagnostics.Q_TARGETS].append(
        {"nodeId": TARGET_B, "name": "измеримость", "description": "  ", "status": "active"}
    )
    report = diagnostics.collect()
    issue = next(i for i in report["issues"] if i["code"] == "targets_without_description")
    assert issue["severity"] == "error"
    assert issue["items"][0]["nodeId"] == TARGET_B, "нужен nodeId, чтобы перейти к объекту"


def test_finds_spelling_twins(db):
    """Ровно эта пара узлов приводила к ложным нарушениям."""
    db.rows[diagnostics.Q_TARGETS] = [
        {"nodeId": TARGET_A, "name": "срок исполнения", "description": "о", "status": "active"},
        {"nodeId": TARGET_B, "name": "срок_исполнения", "description": "о", "status": "active"},
    ]
    db.rows[diagnostics.Q_TARGET_USAGE] = [
        {"name": "срок исполнения", "rule_count": 1}, {"name": "срок_исполнения", "rule_count": 1}
    ]
    issue = next(i for i in diagnostics.collect()["issues"] if i["code"] == "duplicate_check_targets")
    assert issue["severity"] == "error"
    assert "срок исполнения" in issue["items"][0]["label"]
    assert "срок_исполнения" in issue["items"][0]["label"]


def test_finds_missing_identifiers_and_offers_a_fix(db):
    _healthy(db)
    db.rows[diagnostics.Q_MISSING_IDS] = [{"nodeId": ORDER, "kind": "Order", "label": "ПР-01"}]
    issue = next(i for i in diagnostics.collect()["issues"] if i["code"] == "missing_identifiers")
    assert issue["severity"] == "error"
    assert issue["fix"]["action"] == "repair_identifiers"
    assert "приказ" in issue["items"][0]["label"]


def test_finds_rules_without_target(db):
    _healthy(db)
    db.rows[diagnostics.Q_RULES_WITHOUT_TARGET] = [{"nodeId": RULE, "label": "R-1.1"}]
    issue = next(i for i in diagnostics.collect()["issues"] if i["code"] == "rules_without_target")
    assert issue["severity"] == "error"


def test_orphan_targets_are_only_a_warning(db):
    _healthy(db)
    db.rows[diagnostics.Q_TARGET_USAGE] = []
    report = diagnostics.collect()
    issue = next(i for i in report["issues"] if i["code"] == "orphan_check_targets")
    assert issue["severity"] == "warning"
    assert report["ready"] is True, "предупреждения не должны блокировать готовность"


def test_example_kind_mismatch(db):
    """Запрету нужны примеры нарушений, требованию — образцы. Иначе examples пуст."""
    _healthy(db)
    db.rows[diagnostics.Q_EXAMPLE_COVERAGE] = [
        {"nodeId": RULE, "label": "R-1.1", "type": "REQUIREMENT",
         "total": 2, "violating": 2, "correct": 0},
    ]
    issue = next(i for i in diagnostics.collect()["issues"] if i["code"] == "example_kind_mismatch")
    assert issue["severity"] == "warning"


def test_rules_without_examples_is_info(db):
    _healthy(db)
    db.rows[diagnostics.Q_EXAMPLE_COVERAGE] = [
        {"nodeId": RULE, "label": "R-1.1", "type": "REQUIREMENT",
         "total": 0, "violating": 0, "correct": 0},
    ]
    issue = next(i for i in diagnostics.collect()["issues"] if i["code"] == "rules_without_examples")
    assert issue["severity"] == "info"


def test_archived_targets_are_not_diagnosed(db):
    """Архивные узлы не участвуют в проверках, ругаться на них незачем."""
    _healthy(db)
    db.rows[diagnostics.Q_TARGETS].append(
        {"nodeId": TARGET_B, "name": "старый", "description": "", "status": "archived"}
    )
    assert "targets_without_description" not in codes(diagnostics.collect())


def test_problems_are_flat_strings_for_ready(db):
    db.rows[diagnostics.Q_TARGETS] = [
        {"nodeId": TARGET_B, "name": "измеримость", "description": "", "status": "active"}
    ]
    db.rows[diagnostics.Q_TARGET_USAGE] = [{"name": "измеримость", "rule_count": 1}]
    report = diagnostics.collect()
    assert report["problems"] and all(isinstance(p, str) for p in report["problems"])
