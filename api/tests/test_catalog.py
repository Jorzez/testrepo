"""Тесты каталога: сборка дерева, адресация по nodeId, мягкое удаление.

Neo4j не нужен — низкоуровневые _run/_one подменяются диспетчером по тексту
запроса, поэтому проверяется логика, а не драйвер.
"""

import pytest

import catalog
from catalog import Conflict, NotFound

ORDER_NODE = "4:db:1"
CLAUSE_NODE = "4:db:2"
RULE_NODE = "4:db:3"
EXAMPLE_NODE = "4:db:4"

FETCH = """
        MATCH (n) WHERE elementId(n) = $node_id
        RETURN labels(n) AS labels, properties(n) AS props, elementId(n) AS nodeId
        """


@pytest.fixture
def db(monkeypatch):
    rows: dict[str, list[dict]] = {}
    calls: list[tuple[str, dict]] = []

    def fake_run(query, **params):
        calls.append((query, params))
        return rows.get(query, [])

    def fake_one(query, **params):
        result = fake_run(query, **params)
        return result[0] if result else None

    monkeypatch.setattr(catalog, "_run", fake_run)
    monkeypatch.setattr(catalog, "_one", fake_one)
    return type("DB", (), {"rows": rows, "calls": calls})


def _exists(db, node_id, labels, **props):
    db.rows[FETCH] = db.rows.get(FETCH, []) + [
        {"labels": labels, "props": props, "nodeId": node_id}
    ]


# ------------------------------ slugify_id ----------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [("ПР-01", "пр_01"), ("3.1", "3.1"), ("  Раздел  IV ", "раздел_iv"), ("!!!", "id")],
)
def test_slugify(value, expected):
    assert catalog.slugify_id(value) == expected


# ------------------------------ build_tree ----------------------------------


def _seed(db, order_props=None, clause_props=None, rule_props=None):
    db.rows[catalog.Q_ORDERS] = [
        {"nodeId": ORDER_NODE, "props": order_props or {"number": "ПР-01", "status": "active"}},
    ]
    db.rows[catalog.Q_CLAUSES] = [
        {"parent": ORDER_NODE, "nodeId": CLAUSE_NODE,
         "props": clause_props or {"code": "1.1", "text": "текст"}},
    ]
    db.rows[catalog.Q_RULES] = [
        {"parent": CLAUSE_NODE, "nodeId": RULE_NODE,
         "props": rule_props or {"ruleId": "R-1.1", "type": "REQUIREMENT"}},
    ]
    db.rows[catalog.Q_RULE_TARGETS] = [{"parent": RULE_NODE, "name": "проект"}]
    db.rows[catalog.Q_EXAMPLES] = [
        {"parent": RULE_NODE, "nodeId": EXAMPLE_NODE,
         "props": {"exampleId": "EX-1", "text": "пример", "isViolation": False}}
    ]
    db.rows[catalog.Q_CLAUSE_REFS] = []
    return db


def test_tree_nests_and_carries_node_ids(db):
    """nodeId обязателен на каждом уровне: по нему интерфейс раскрывает карточки."""
    _seed(db)
    order = catalog.build_tree()["orders"][0]
    assert order["nodeId"] == ORDER_NODE
    clause = order["clauses"][0]
    assert clause["nodeId"] == CLAUSE_NODE
    rule = clause["rules"][0]
    assert rule["nodeId"] == RULE_NODE
    assert rule["targets"] == ["проект"]
    assert rule["examples"][0]["nodeId"] == EXAMPLE_NODE


def test_tree_works_without_business_keys(db):
    """Регрессия: у узлов может не быть orderId/clauseId — дерево всё равно строится."""
    _seed(db, order_props={"number": "ПР-01"}, clause_props={"code": "1.1", "text": "т"},
          rule_props={"type": "REQUIREMENT", "description": "п"})
    order = catalog.build_tree()["orders"][0]
    assert order["nodeId"] == ORDER_NODE
    assert "orderId" not in order
    assert order["status"] == "active", "узел без status считается активным"
    assert order["clauses"][0]["rules"][0]["nodeId"] == RULE_NODE


def test_tree_hides_archived_by_default(db):
    _seed(db, order_props={"number": "ПР-01", "status": "archived"})
    assert catalog.build_tree()["orders"] == []
    assert len(catalog.build_tree(include_archived=True)["orders"]) == 1


def test_tree_hides_archived_rule_and_example(db):
    _seed(db, rule_props={"ruleId": "R-1.1", "status": "archived"})
    assert catalog.build_tree()["orders"][0]["clauses"][0]["rules"] == []


def test_tree_serializes_temporal_values(db):
    class FakeDate:
        def __str__(self):
            return "2024-03-01"

    _seed(db, order_props={"number": "ПР-01", "date": FakeDate()})
    assert catalog.build_tree()["orders"][0]["date"] == "2024-03-01"


def test_tree_includes_clause_references(db):
    _seed(db)
    db.rows[catalog.Q_CLAUSE_REFS] = [
        {"parent": CLAUSE_NODE, "nodeId": "4:db:9", "code": "2.5"}
    ]
    refs = catalog.build_tree()["orders"][0]["clauses"][0]["references"]
    assert refs == [{"nodeId": "4:db:9", "code": "2.5"}]


def test_check_targets_list(db):
    db.rows[catalog.Q_TARGETS] = [
        {"nodeId": "4:db:7", "props": {"name": "проект"}, "rules": ["R-1.1", None]},
    ]
    target = catalog.list_check_targets()[0]
    assert target["nodeId"] == "4:db:7"
    assert target["description"] == ""
    assert target["rules"] == ["R-1.1"], "пустые значения из collect отфильтрованы"


# --------------------------- защита от двойников ----------------------------


@pytest.mark.parametrize("existing", ["срок исполнения", "Срок-Исполнения", "СРОК_ИСПОЛНЕНИЯ"])
def test_create_target_rejects_spelling_twin(db, existing):
    db.rows["MATCH (t:CheckTarget) RETURN t.name AS name"] = [{"name": existing}]
    with pytest.raises(Conflict) as exc:
        catalog.create_check_target("срок_исполнения", "описание")
    assert existing in str(exc.value)


# ------------------------- правка произвольных свойств ----------------------


def test_properties_reject_status(db):
    _exists(db, ORDER_NODE, ["Order"], number="ПР-01")
    with pytest.raises(Conflict) as exc:
        catalog.update_properties(ORDER_NODE, {"status": "archived"})
    assert "отдельной операцией" in str(exc.value)


def test_properties_reject_empty_business_key(db):
    _exists(db, ORDER_NODE, ["Order"], orderId="PR-01")
    with pytest.raises(Conflict) as exc:
        catalog.update_properties(ORDER_NODE, {"orderId": ""})
    assert "нельзя очистить" in str(exc.value)


def test_properties_reject_duplicate_business_key(db):
    _exists(db, ORDER_NODE, ["Order"], orderId="PR-01")
    db.rows["MATCH (n:Order {orderId: $value}) WHERE elementId(n) <> $node_id "
            "RETURN elementId(n) AS nodeId"] = [{"nodeId": "4:db:99"}]
    with pytest.raises(Conflict) as exc:
        catalog.update_properties(ORDER_NODE, {"orderId": "PR-02"})
    assert "уже занят" in str(exc.value)


def test_properties_missing_node(db):
    with pytest.raises(NotFound):
        catalog.update_properties("4:db:404", {"title": "x"})


def test_properties_date_handled_separately(db):
    """date — временной тип, его нельзя записать через SET n += $map."""
    _exists(db, ORDER_NODE, ["Order"], number="ПР-01")
    catalog.update_properties(ORDER_NODE, {"title": "новый", "date": "2024-03-01"})
    queries = [q for q, _ in db.calls]
    assert any("SET n += $props" in q for q in queries)
    assert any("date($value)" in q for q in queries)


# ------------------------------ мягкое удаление -----------------------------


def test_delete_refuses_active_node(db):
    _exists(db, ORDER_NODE, ["Order"], number="ПР-01", status="active")
    with pytest.raises(Conflict) as exc:
        catalog.delete_node(ORDER_NODE)
    assert "архивированный" in str(exc.value)


def test_delete_example_does_not_require_archive(db):
    """Примеры дёшево пересоздаются, поэтому не требуют архивирования."""
    _exists(db, EXAMPLE_NODE, ["ViolationExample"], text="пример")
    assert catalog.delete_node(EXAMPLE_NODE)["deleted"] == EXAMPLE_NODE


def test_delete_target_refuses_while_used(db):
    _exists(db, "4:db:7", ["CheckTarget"], name="проект", status="archived")
    db.rows["MATCH (r:Rule)-[:APPLIES_TO]->(t) WHERE elementId(t) = $node_id "
            "RETURN r.ruleId AS rule_id"] = [{"rule_id": "R-1.1"}]
    with pytest.raises(Conflict) as exc:
        catalog.delete_node("4:db:7")
    assert "R-1.1" in str(exc.value)


def test_status_is_validated(db):
    with pytest.raises(Conflict):
        catalog.set_status(ORDER_NODE, "deleted")


def test_rule_type_is_validated():
    with pytest.raises(Conflict):
        catalog._validate_rule_type("OBLIGATION")


# ------------------------------ связи ---------------------------------------


def test_set_rule_targets_rejects_unknown(db):
    _exists(db, RULE_NODE, ["Rule"], ruleId="R-1.1")
    db.rows["MATCH (t:CheckTarget) RETURN t.name AS name"] = [{"name": "проект"}]
    with pytest.raises(NotFound) as exc:
        catalog.set_rule_targets(RULE_NODE, ["проект", "выдумка"])
    assert "выдумка" in str(exc.value)


def test_set_rule_targets_clears_old_links(db):
    _exists(db, RULE_NODE, ["Rule"], ruleId="R-1.1")
    db.rows["MATCH (t:CheckTarget) RETURN t.name AS name"] = [{"name": "проект"}]
    catalog.set_rule_targets(RULE_NODE, ["проект"])
    assert any("DELETE rel" in q for q, _ in db.calls)


def test_clause_cannot_reference_itself(db):
    _exists(db, CLAUSE_NODE, ["Clause"], code="1.1")
    with pytest.raises(Conflict):
        catalog.set_clause_references(CLAUSE_NODE, [CLAUSE_NODE])


def test_fetch_node_checks_label(db):
    _exists(db, CLAUSE_NODE, ["Clause"], code="1.1")
    with pytest.raises(Conflict) as exc:
        catalog.create_clause(CLAUSE_NODE, "1.2", "текст")
    assert "Ожидался узел :Order" in str(exc.value)
