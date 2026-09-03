"""Тесты каталога: сборка дерева, мягкое удаление, защита от двойников.

Neo4j не нужен — низкоуровневые _run/_one подменяются диспетчером по тексту
запроса, поэтому проверяется именно логика, а не драйвер.
"""

import pytest

import catalog
from catalog import Conflict, NotFound


@pytest.fixture
def db(monkeypatch):
    """Подменяет доступ к базе. rows — ответы по константам запросов."""
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


# ------------------------------ slugify_id ----------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [("ПР-01", "пр_01"), ("3.1", "3.1"), ("  Раздел  IV ", "раздел_iv"), ("!!!", "id")],
)
def test_slugify(value, expected):
    assert catalog.slugify_id(value) == expected


# ------------------------------ build_tree ----------------------------------


def _seed_tree(db, *, clause_status="active", rule_status="active"):
    db.rows[catalog.Q_ORDERS] = [
        {"props": {"orderId": "PR-01", "number": "ПР-01", "title": "О целях", "status": "active"}},
        {"props": {"orderId": "PR-99", "number": "ПР-99", "title": "Старый", "status": "archived"}},
    ]
    db.rows[catalog.Q_CLAUSES] = [
        {"orderId": "PR-01", "props": {"clauseId": "PR-01/1.1", "code": "1.1",
                                       "text": "текст", "status": clause_status}},
    ]
    db.rows[catalog.Q_RULES] = [
        {"clauseId": "PR-01/1.1", "props": {"ruleId": "R-1.1", "type": "REQUIREMENT",
                                            "description": "правило", "status": rule_status}},
    ]
    db.rows[catalog.Q_RULE_TARGETS] = [{"ruleId": "R-1.1", "name": "проект"}]
    db.rows[catalog.Q_EXAMPLES] = [
        {"ruleId": "R-1.1", "props": {"exampleId": "EX-1", "text": "пример",
                                      "isViolation": False, "status": "active"}}
    ]


def test_tree_nests_orders_clauses_rules(db):
    _seed_tree(db)
    tree = catalog.build_tree()
    assert [o["orderId"] for o in tree["orders"]] == ["PR-01"], "архивный приказ не показывается"
    order = tree["orders"][0]
    rule = order["clauses"][0]["rules"][0]
    assert rule["targets"] == ["проект"]
    assert rule["examples"][0]["exampleId"] == "EX-1"


def test_tree_includes_archived_on_demand(db):
    _seed_tree(db)
    tree = catalog.build_tree(include_archived=True)
    assert {o["orderId"] for o in tree["orders"]} == {"PR-01", "PR-99"}


def test_tree_hides_archived_clause(db):
    _seed_tree(db, clause_status="archived")
    assert catalog.build_tree()["orders"][0]["clauses"] == []


def test_tree_hides_archived_rule(db):
    _seed_tree(db, rule_status="archived")
    assert catalog.build_tree()["orders"][0]["clauses"][0]["rules"] == []


def test_tree_treats_missing_status_as_active(db):
    """Узлы, заведённые до появления status, не должны исчезать из каталога."""
    db.rows[catalog.Q_ORDERS] = [{"props": {"orderId": "PR-01", "number": "ПР-01"}}]
    orders = catalog.build_tree()["orders"]
    assert len(orders) == 1
    assert orders[0]["status"] == "active"


def test_tree_serializes_date(db):
    class FakeDate:
        def __str__(self):
            return "2024-03-01"

    db.rows[catalog.Q_ORDERS] = [
        {"props": {"orderId": "PR-01", "number": "ПР-01", "date": FakeDate()}}
    ]
    assert catalog.build_tree()["orders"][0]["date"] == "2024-03-01"


def test_check_targets_list_marks_missing_description(db):
    db.rows[catalog.Q_TARGETS] = [
        {"props": {"name": "проект"}, "rules": ["R-1.1", None]},
    ]
    target = catalog.list_check_targets()[0]
    assert target["description"] == ""
    assert target["rules"] == ["R-1.1"], "пустые значения из collect отфильтрованы"


# --------------------------- защита от двойников ----------------------------


@pytest.mark.parametrize("existing", ["срок исполнения", "Срок-Исполнения", "СРОК_ИСПОЛНЕНИЯ"])
def test_create_target_rejects_spelling_twin(db, existing):
    """Ровно эта пара узлов и приводила к ложным нарушениям."""
    db.rows["MATCH (t:CheckTarget) RETURN t.name AS name"] = [{"name": existing}]
    with pytest.raises(Conflict) as exc:
        catalog.create_check_target("срок_исполнения", "описание")
    assert existing in str(exc.value)


def test_create_target_allows_distinct_name(db):
    db.rows["MATCH (t:CheckTarget) RETURN t.name AS name"] = [{"name": "проект"}]
    created = {"props": {"name": "измеримость", "description": "d", "status": "active"}}
    db.rows[
        """
        CREATE (t:CheckTarget {name: $name, description: $description, status: $status})
        RETURN properties(t) AS props
        """
    ] = [created]
    assert catalog.create_check_target("измеримость", "d")["name"] == "измеримость"


# ------------------------- валидация и мягкое удаление ----------------------


def test_rule_type_is_validated():
    with pytest.raises(Conflict):
        catalog._validate_rule_type("OBLIGATION")


def test_status_is_validated():
    with pytest.raises(Conflict):
        catalog._require_status("deleted")


def test_delete_order_refuses_active(db):
    query = f"MATCH (o:Order {{orderId: $id}}) RETURN {catalog.ACTIVE.format('o')} AS is_active"
    db.rows[query] = [{"is_active": True}]
    with pytest.raises(Conflict) as exc:
        catalog.delete_order("PR-01")
    assert "архивированный" in str(exc.value)


def test_delete_order_missing(db):
    with pytest.raises(NotFound):
        catalog.delete_order("PR-XX")


def test_delete_rule_refuses_active(db):
    query = f"MATCH (r:Rule {{ruleId: $id}}) RETURN {catalog.ACTIVE.format('r')} AS is_active"
    db.rows[query] = [{"is_active": True}]
    with pytest.raises(Conflict):
        catalog.delete_rule("R-1.1")


def test_delete_check_target_refuses_while_used(db):
    query = f"""
        MATCH (t:CheckTarget {{name: $name}})
        OPTIONAL MATCH (r:Rule)-[:APPLIES_TO]->(t)
        RETURN {catalog.ACTIVE.format('t')} AS is_active, collect(DISTINCT r.ruleId) AS rules
        """
    db.rows[query] = [{"is_active": False, "rules": ["R-1.1"]}]
    with pytest.raises(Conflict) as exc:
        catalog.delete_check_target("проект")
    assert "R-1.1" in str(exc.value)


# ------------------------------ привязка правил -----------------------------


def test_set_rule_targets_rejects_unknown(db):
    db.rows["MATCH (r:Rule {ruleId: $id}) RETURN r.ruleId AS id"] = [{"id": "R-1.1"}]
    db.rows["MATCH (t:CheckTarget) RETURN t.name AS name"] = [{"name": "проект"}]
    with pytest.raises(NotFound) as exc:
        catalog.set_rule_targets("R-1.1", ["проект", "выдумка"])
    assert "выдумка" in str(exc.value)


def test_set_rule_targets_missing_rule(db):
    with pytest.raises(NotFound):
        catalog.set_rule_targets("R-XX", [])


def test_set_rule_targets_clears_old_links(db):
    db.rows["MATCH (r:Rule {ruleId: $id}) RETURN r.ruleId AS id"] = [{"id": "R-1.1"}]
    db.rows["MATCH (t:CheckTarget) RETURN t.name AS name"] = [{"name": "проект"}]
    catalog.set_rule_targets("R-1.1", ["проект"])
    deletes = [q for q, _ in db.calls if "DELETE rel" in q]
    assert deletes, "старые связи APPLIES_TO должны удаляться перед записью новых"


def test_create_clause_requires_existing_order(db):
    with pytest.raises(NotFound):
        catalog.create_clause("PR-XX", "1.1", "текст")


def test_create_rule_requires_existing_clause(db):
    with pytest.raises(NotFound):
        catalog.create_rule("PR-01/9.9", "REQUIREMENT", "правило")
