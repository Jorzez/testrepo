"""CRUD над каталогом нормативных требований.

Модель редактирования — мягкое удаление: узел получает status='archived',
выпадает из проверок (см. фильтры в graph.py), но остаётся в графе вместе
с историей. Физическое удаление разрешено только для уже архивированного
узла — чтобы «удалить» никогда не означало «потерять» с первого клика.

Узлы, заведённые до появления status, считаются активными (coalesce).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from graph import ACTIVE, get_driver
from naming import normalize_name

log = logging.getLogger(__name__)

ACTIVE_STATUS = "active"
ARCHIVED_STATUS = "archived"
STATUSES = (ACTIVE_STATUS, ARCHIVED_STATUS)

RULE_TYPES = ("PROHIBITION", "REQUIREMENT")


class CatalogError(RuntimeError):
    """Базовая ошибка каталога."""


class NotFound(CatalogError):
    """Узел не найден."""


class Conflict(CatalogError):
    """Операция противоречит текущему состоянию графа."""


# --------------------------------------------------------------------------
#  Вспомогательное
# --------------------------------------------------------------------------


def _run(query: str, **params) -> list[dict[str, Any]]:
    with get_driver().session() as session:
        return [dict(record) for record in session.run(query, **params)]


def _one(query: str, **params) -> Optional[dict[str, Any]]:
    rows = _run(query, **params)
    return rows[0] if rows else None


def slugify_id(value: str) -> str:
    """Превращает произвольную строку в безопасный идентификатор."""
    text = normalize_name(value)
    text = re.sub(r"[^0-9a-zа-я_.\-/]+", "", text)
    return text.strip("_") or "id"


def _require_status(status: str) -> str:
    if status not in STATUSES:
        raise Conflict(f"Недопустимый статус {status!r}, ожидался один из {STATUSES}")
    return status


# --------------------------------------------------------------------------
#  Чтение: дерево каталога
# --------------------------------------------------------------------------

Q_ORDERS = "MATCH (o:Order) RETURN properties(o) AS props"
Q_CLAUSES = """
MATCH (o:Order)-[:CONTAINS]->(c:Clause)
RETURN o.orderId AS orderId, properties(c) AS props
"""
Q_RULES = """
MATCH (c:Clause)-[:DEFINES]->(r:Rule)
RETURN c.clauseId AS clauseId, properties(r) AS props
"""
Q_RULE_TARGETS = """
MATCH (r:Rule)-[:APPLIES_TO]->(t:CheckTarget)
RETURN r.ruleId AS ruleId, t.name AS name
ORDER BY name
"""
Q_EXAMPLES = """
MATCH (r:Rule)-[:HAS_EXAMPLE]->(e:ViolationExample)
RETURN r.ruleId AS ruleId, properties(e) AS props
"""
Q_TARGETS = """
MATCH (t:CheckTarget)
OPTIONAL MATCH (r:Rule)-[:APPLIES_TO]->(t)
RETURN properties(t) AS props, collect(DISTINCT r.ruleId) AS rules
"""


def _status_of(props: dict[str, Any]) -> str:
    return props.get("status") or ACTIVE_STATUS


def _keep(props: dict[str, Any], include_archived: bool) -> bool:
    return include_archived or _status_of(props) == ACTIVE_STATUS


def build_tree(include_archived: bool = False) -> dict[str, Any]:
    """Весь каталог одним ответом: приказы → пункты → правила → атрибуты и примеры.

    Собирается из нескольких плоских запросов и склеивается в Python:
    так проще читать и тестировать, чем одну вложенную агрегацию в Cypher.
    """
    orders = [r["props"] for r in _run(Q_ORDERS)]
    clauses = _run(Q_CLAUSES)
    rules = _run(Q_RULES)
    rule_targets = _run(Q_RULE_TARGETS)
    examples = _run(Q_EXAMPLES)

    targets_by_rule: dict[str, list[str]] = {}
    for row in rule_targets:
        targets_by_rule.setdefault(row["ruleId"], []).append(row["name"])

    examples_by_rule: dict[str, list[dict]] = {}
    for row in examples:
        if _keep(row["props"], include_archived):
            examples_by_rule.setdefault(row["ruleId"], []).append(row["props"])

    rules_by_clause: dict[str, list[dict]] = {}
    for row in rules:
        props = row["props"]
        if not _keep(props, include_archived):
            continue
        rule_id = props.get("ruleId")
        node = {
            **props,
            "status": _status_of(props),
            "targets": sorted(targets_by_rule.get(rule_id, [])),
            "examples": sorted(
                examples_by_rule.get(rule_id, []), key=lambda e: str(e.get("exampleId"))
            ),
        }
        rules_by_clause.setdefault(row["clauseId"], []).append(node)

    clauses_by_order: dict[str, list[dict]] = {}
    for row in clauses:
        props = row["props"]
        if not _keep(props, include_archived):
            continue
        clause_id = props.get("clauseId")
        node = {
            **props,
            "status": _status_of(props),
            "rules": sorted(rules_by_clause.get(clause_id, []), key=lambda r: str(r.get("ruleId"))),
        }
        clauses_by_order.setdefault(row["orderId"], []).append(node)

    tree = []
    for props in orders:
        if not _keep(props, include_archived):
            continue
        order_id = props.get("orderId")
        tree.append(
            {
                **props,
                "date": str(props["date"]) if props.get("date") is not None else None,
                "status": _status_of(props),
                "clauses": sorted(
                    clauses_by_order.get(order_id, []), key=lambda c: str(c.get("code"))
                ),
            }
        )

    tree.sort(key=lambda o: str(o.get("number") or o.get("orderId")))
    return {"orders": tree}


def list_check_targets(include_archived: bool = False) -> list[dict[str, Any]]:
    """Атрибуты со списком правил, которые на них ссылаются."""
    result = []
    for row in _run(Q_TARGETS):
        props = row["props"]
        if not _keep(props, include_archived):
            continue
        result.append(
            {
                **props,
                "description": props.get("description") or "",
                "status": _status_of(props),
                "rules": sorted(r for r in row["rules"] if r),
            }
        )
    result.sort(key=lambda t: str(t.get("name")))
    return result


# --------------------------------------------------------------------------
#  Приказы
# --------------------------------------------------------------------------


def create_order(
    number: str, title: str, date: str | None = None, order_id: str | None = None
) -> dict[str, Any]:
    order_id = order_id or slugify_id(number)
    if _one("MATCH (o:Order {orderId: $id}) RETURN o.orderId AS id", id=order_id):
        raise Conflict(f"Приказ с идентификатором {order_id!r} уже существует")

    row = _one(
        """
        CREATE (o:Order {orderId: $id, number: $number, title: $title, status: $status})
        SET o.date = CASE WHEN $date IS NULL THEN NULL ELSE date($date) END
        RETURN properties(o) AS props
        """,
        id=order_id,
        number=number,
        title=title,
        date=date,
        status=ACTIVE_STATUS,
    )
    log.info("Создан приказ %s (%s)", order_id, number)
    return row["props"]


def update_order(order_id: str, **fields) -> dict[str, Any]:
    row = _one(
        """
        MATCH (o:Order {orderId: $id})
        SET o.number = coalesce($number, o.number),
            o.title  = coalesce($title, o.title),
            o.date   = CASE WHEN $date IS NULL THEN o.date ELSE date($date) END
        RETURN properties(o) AS props
        """,
        id=order_id,
        number=fields.get("number"),
        title=fields.get("title"),
        date=fields.get("date"),
    )
    if not row:
        raise NotFound(f"Приказ {order_id!r} не найден")
    return row["props"]


def set_order_status(order_id: str, status: str) -> dict[str, Any]:
    row = _one(
        "MATCH (o:Order {orderId: $id}) SET o.status = $status RETURN properties(o) AS props",
        id=order_id,
        status=_require_status(status),
    )
    if not row:
        raise NotFound(f"Приказ {order_id!r} не найден")
    log.info("Приказ %s -> %s", order_id, status)
    return row["props"]


def delete_order(order_id: str) -> dict[str, int]:
    """Физическое удаление приказа со всем содержимым. Только из архива."""
    row = _one(
        f"MATCH (o:Order {{orderId: $id}}) RETURN {ACTIVE.format('o')} AS is_active",
        id=order_id,
    )
    if row is None:
        raise NotFound(f"Приказ {order_id!r} не найден")
    if row["is_active"]:
        raise Conflict(
            "Удалять можно только архивированный приказ. Сначала отправьте его в архив."
        )

    stats = _one(
        """
        MATCH (o:Order {orderId: $id})
        OPTIONAL MATCH (o)-[:CONTAINS]->(c:Clause)
        OPTIONAL MATCH (c)-[:DEFINES]->(r:Rule)
        OPTIONAL MATCH (r)-[:HAS_EXAMPLE]->(e:ViolationExample)
        WITH o, collect(DISTINCT c) AS cs, collect(DISTINCT r) AS rs, collect(DISTINCT e) AS es
        WITH o, cs, rs, es, size(cs) AS clauses, size(rs) AS rules, size(es) AS examples
        FOREACH (x IN es | DETACH DELETE x)
        FOREACH (x IN rs | DETACH DELETE x)
        FOREACH (x IN cs | DETACH DELETE x)
        DETACH DELETE o
        RETURN clauses, rules, examples
        """,
        id=order_id,
    )
    log.warning("Удалён приказ %s: %s", order_id, stats)
    return stats or {"clauses": 0, "rules": 0, "examples": 0}


# --------------------------------------------------------------------------
#  Пункты
# --------------------------------------------------------------------------


def create_clause(
    order_id: str, code: str, text: str, clause_id: str | None = None
) -> dict[str, Any]:
    if not _one("MATCH (o:Order {orderId: $id}) RETURN o.orderId AS id", id=order_id):
        raise NotFound(f"Приказ {order_id!r} не найден")

    clause_id = clause_id or f"{order_id}/{slugify_id(code)}"
    if _one("MATCH (c:Clause {clauseId: $id}) RETURN c.clauseId AS id", id=clause_id):
        raise Conflict(f"Пункт с идентификатором {clause_id!r} уже существует")

    row = _one(
        """
        MATCH (o:Order {orderId: $order_id})
        CREATE (c:Clause {clauseId: $id, code: $code, text: $text, status: $status})
        CREATE (o)-[:CONTAINS]->(c)
        RETURN properties(c) AS props
        """,
        order_id=order_id,
        id=clause_id,
        code=code,
        text=text,
        status=ACTIVE_STATUS,
    )
    log.info("Создан пункт %s в приказе %s", clause_id, order_id)
    return row["props"]


def update_clause(clause_id: str, **fields) -> dict[str, Any]:
    row = _one(
        """
        MATCH (c:Clause {clauseId: $id})
        SET c.code = coalesce($code, c.code),
            c.text = coalesce($text, c.text)
        RETURN properties(c) AS props
        """,
        id=clause_id,
        code=fields.get("code"),
        text=fields.get("text"),
    )
    if not row:
        raise NotFound(f"Пункт {clause_id!r} не найден")
    return row["props"]


def set_clause_status(clause_id: str, status: str) -> dict[str, Any]:
    row = _one(
        "MATCH (c:Clause {clauseId: $id}) SET c.status = $status RETURN properties(c) AS props",
        id=clause_id,
        status=_require_status(status),
    )
    if not row:
        raise NotFound(f"Пункт {clause_id!r} не найден")
    return row["props"]


def delete_clause(clause_id: str) -> dict[str, int]:
    row = _one(
        f"MATCH (c:Clause {{clauseId: $id}}) RETURN {ACTIVE.format('c')} AS is_active",
        id=clause_id,
    )
    if row is None:
        raise NotFound(f"Пункт {clause_id!r} не найден")
    if row["is_active"]:
        raise Conflict("Удалять можно только архивированный пункт.")

    stats = _one(
        """
        MATCH (c:Clause {clauseId: $id})
        OPTIONAL MATCH (c)-[:DEFINES]->(r:Rule)
        OPTIONAL MATCH (r)-[:HAS_EXAMPLE]->(e:ViolationExample)
        WITH c, collect(DISTINCT r) AS rs, collect(DISTINCT e) AS es
        WITH c, rs, es, size(rs) AS rules, size(es) AS examples
        FOREACH (x IN es | DETACH DELETE x)
        FOREACH (x IN rs | DETACH DELETE x)
        DETACH DELETE c
        RETURN rules, examples
        """,
        id=clause_id,
    )
    log.warning("Удалён пункт %s: %s", clause_id, stats)
    return stats or {"rules": 0, "examples": 0}


# --------------------------------------------------------------------------
#  Правила
# --------------------------------------------------------------------------


def _validate_rule_type(rule_type: str) -> str:
    if rule_type not in RULE_TYPES:
        raise Conflict(f"Недопустимый тип правила {rule_type!r}, ожидался один из {RULE_TYPES}")
    return rule_type


def create_rule(
    clause_id: str,
    rule_type: str,
    description: str,
    check_instruction: str = "",
    targets: list[str] | None = None,
    rule_id: str | None = None,
) -> dict[str, Any]:
    clause = _one(
        "MATCH (c:Clause {clauseId: $id}) RETURN c.code AS code", id=clause_id
    )
    if not clause:
        raise NotFound(f"Пункт {clause_id!r} не найден")
    _validate_rule_type(rule_type)

    rule_id = rule_id or f"R-{slugify_id(clause['code'])}"
    if _one("MATCH (r:Rule {ruleId: $id}) RETURN r.ruleId AS id", id=rule_id):
        raise Conflict(f"Правило с идентификатором {rule_id!r} уже существует")

    row = _one(
        """
        MATCH (c:Clause {clauseId: $clause_id})
        CREATE (r:Rule {ruleId: $id, type: $type, description: $description,
                        checkInstruction: $instruction, status: $status})
        CREATE (c)-[:DEFINES]->(r)
        RETURN properties(r) AS props
        """,
        clause_id=clause_id,
        id=rule_id,
        type=rule_type,
        description=description,
        instruction=check_instruction,
        status=ACTIVE_STATUS,
    )
    if targets:
        set_rule_targets(rule_id, targets)
    log.info("Создано правило %s (%s) в пункте %s", rule_id, rule_type, clause_id)
    return row["props"]


def update_rule(rule_id: str, **fields) -> dict[str, Any]:
    if fields.get("type") is not None:
        _validate_rule_type(fields["type"])
    row = _one(
        """
        MATCH (r:Rule {ruleId: $id})
        SET r.type             = coalesce($type, r.type),
            r.description      = coalesce($description, r.description),
            r.checkInstruction = coalesce($instruction, r.checkInstruction)
        RETURN properties(r) AS props
        """,
        id=rule_id,
        type=fields.get("type"),
        description=fields.get("description"),
        instruction=fields.get("check_instruction"),
    )
    if not row:
        raise NotFound(f"Правило {rule_id!r} не найдено")
    return row["props"]


def set_rule_targets(rule_id: str, targets: list[str]) -> list[str]:
    """Полностью заменяет набор атрибутов правила."""
    if not _one("MATCH (r:Rule {ruleId: $id}) RETURN r.ruleId AS id", id=rule_id):
        raise NotFound(f"Правило {rule_id!r} не найдено")

    known = {t["name"] for t in _run("MATCH (t:CheckTarget) RETURN t.name AS name")}
    unknown = [t for t in targets if t not in known]
    if unknown:
        raise NotFound("Нет таких атрибутов: " + ", ".join(unknown))

    _run("MATCH (:Rule {ruleId: $id})-[rel:APPLIES_TO]->() DELETE rel", id=rule_id)
    if targets:
        _run(
            """
            MATCH (r:Rule {ruleId: $id})
            UNWIND $targets AS name
            MATCH (t:CheckTarget {name: name})
            MERGE (r)-[:APPLIES_TO]->(t)
            """,
            id=rule_id,
            targets=targets,
        )
    log.info("Правило %s теперь применяется к %s", rule_id, targets)
    return targets


def set_rule_status(rule_id: str, status: str) -> dict[str, Any]:
    row = _one(
        "MATCH (r:Rule {ruleId: $id}) SET r.status = $status RETURN properties(r) AS props",
        id=rule_id,
        status=_require_status(status),
    )
    if not row:
        raise NotFound(f"Правило {rule_id!r} не найдено")
    return row["props"]


def delete_rule(rule_id: str) -> dict[str, int]:
    row = _one(
        f"MATCH (r:Rule {{ruleId: $id}}) RETURN {ACTIVE.format('r')} AS is_active", id=rule_id
    )
    if row is None:
        raise NotFound(f"Правило {rule_id!r} не найдено")
    if row["is_active"]:
        raise Conflict("Удалять можно только архивированное правило.")

    stats = _one(
        """
        MATCH (r:Rule {ruleId: $id})
        OPTIONAL MATCH (r)-[:HAS_EXAMPLE]->(e:ViolationExample)
        WITH r, collect(DISTINCT e) AS es
        WITH r, es, size(es) AS examples
        FOREACH (x IN es | DETACH DELETE x)
        DETACH DELETE r
        RETURN examples
        """,
        id=rule_id,
    )
    log.warning("Удалено правило %s: %s", rule_id, stats)
    return stats or {"examples": 0}


# --------------------------------------------------------------------------
#  Атрибуты (:CheckTarget)
# --------------------------------------------------------------------------


def create_check_target(name: str, description: str = "") -> dict[str, Any]:
    """Заводит атрибут, не давая создать двойника по написанию.

    Именно двойники («срок исполнения» и «срок_исполнения») приводили к тому,
    что правило висело на одном узле, а модель возвращала другой.
    """
    normalized = normalize_name(name)
    for existing in _run("MATCH (t:CheckTarget) RETURN t.name AS name"):
        if normalize_name(existing["name"]) == normalized:
            raise Conflict(
                f'Атрибут с таким написанием уже есть: "{existing["name"]}". '
                "Двойники ломают проверку — используйте существующий."
            )

    row = _one(
        """
        CREATE (t:CheckTarget {name: $name, description: $description, status: $status})
        RETURN properties(t) AS props
        """,
        name=name,
        description=description,
        status=ACTIVE_STATUS,
    )
    log.info("Создан атрибут %s", name)
    return row["props"]


def update_check_target(name: str, description: str | None = None) -> dict[str, Any]:
    row = _one(
        """
        MATCH (t:CheckTarget {name: $name})
        SET t.description = coalesce($description, t.description)
        RETURN properties(t) AS props
        """,
        name=name,
        description=description,
    )
    if not row:
        raise NotFound(f"Атрибут {name!r} не найден")
    return row["props"]


def set_check_target_status(name: str, status: str) -> dict[str, Any]:
    row = _one(
        "MATCH (t:CheckTarget {name: $name}) SET t.status = $status RETURN properties(t) AS props",
        name=name,
        status=_require_status(status),
    )
    if not row:
        raise NotFound(f"Атрибут {name!r} не найден")
    return row["props"]


def delete_check_target(name: str) -> dict[str, Any]:
    row = _one(
        f"""
        MATCH (t:CheckTarget {{name: $name}})
        OPTIONAL MATCH (r:Rule)-[:APPLIES_TO]->(t)
        RETURN {ACTIVE.format('t')} AS is_active, collect(DISTINCT r.ruleId) AS rules
        """,
        name=name,
    )
    if row is None:
        raise NotFound(f"Атрибут {name!r} не найден")
    if row["is_active"]:
        raise Conflict("Удалять можно только архивированный атрибут.")
    rules = [r for r in row["rules"] if r]
    if rules:
        raise Conflict(
            "Атрибут используется правилами: " + ", ".join(rules) + ". Сначала отвяжите его."
        )

    _run("MATCH (t:CheckTarget {name: $name}) DETACH DELETE t", name=name)
    log.warning("Удалён атрибут %s", name)
    return {"deleted": name}


# --------------------------------------------------------------------------
#  Примеры
# --------------------------------------------------------------------------


def create_example(
    rule_id: str, text: str, is_violation: bool, example_id: str | None = None
) -> dict[str, Any]:
    if not _one("MATCH (r:Rule {ruleId: $id}) RETURN r.ruleId AS id", id=rule_id):
        raise NotFound(f"Правило {rule_id!r} не найдено")

    if not example_id:
        used = _run(
            "MATCH (:Rule {ruleId: $id})-[:HAS_EXAMPLE]->(e) RETURN e.exampleId AS id", id=rule_id
        )
        example_id = f"{rule_id}-EX{len(used) + 1}"
        while _one("MATCH (e:ViolationExample {exampleId: $id}) RETURN e.exampleId AS id", id=example_id):
            example_id = f"{example_id}x"

    row = _one(
        """
        MATCH (r:Rule {ruleId: $rule_id})
        CREATE (e:ViolationExample {exampleId: $id, text: $text,
                                    isViolation: $is_violation, status: $status})
        CREATE (r)-[:HAS_EXAMPLE]->(e)
        RETURN properties(e) AS props
        """,
        rule_id=rule_id,
        id=example_id,
        text=text,
        is_violation=is_violation,
        status=ACTIVE_STATUS,
    )
    return row["props"]


def update_example(example_id: str, **fields) -> dict[str, Any]:
    row = _one(
        """
        MATCH (e:ViolationExample {exampleId: $id})
        SET e.text        = coalesce($text, e.text),
            e.isViolation = coalesce($is_violation, e.isViolation)
        RETURN properties(e) AS props
        """,
        id=example_id,
        text=fields.get("text"),
        is_violation=fields.get("is_violation"),
    )
    if not row:
        raise NotFound(f"Пример {example_id!r} не найден")
    return row["props"]


def delete_example(example_id: str) -> dict[str, Any]:
    """Примеры не архивируются — они дёшево пересоздаются."""
    row = _one(
        "MATCH (e:ViolationExample {exampleId: $id}) DETACH DELETE e RETURN $id AS id",
        id=example_id,
    )
    if not row:
        raise NotFound(f"Пример {example_id!r} не найден")
    return {"deleted": example_id}
