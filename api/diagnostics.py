"""Диагностика графа: что именно мешает проверкам работать честно.

Каждая проверка отвечает на вопрос «как это проявится снаружи». Молчаливая
неполнота хуже явной ошибки: правило, повисшее без атрибута, и атрибут без
описания выглядят как «модель тупит», хотя это дефект данных.

severity:
  error   — проверка целей уже даёт неверный результат; /ready отдаёт 503
  warning — данные противоречивы или бесполезны, но проверка работает
  info    — справочно
"""

from __future__ import annotations

import logging
from typing import Any

from graph import ACTIVE, get_driver
from naming import normalize_name

log = logging.getLogger(__name__)

ERROR, WARNING, INFO = "error", "warning", "info"


def _run(query: str, **params) -> list[dict[str, Any]]:
    with get_driver().session() as session:
        return [dict(record) for record in session.run(query, **params)]


# --------------------------------------------------------------------------
#  Запросы проверок
# --------------------------------------------------------------------------

Q_TARGETS = """
MATCH (t:CheckTarget)
RETURN elementId(t) AS nodeId, t.name AS name,
       coalesce(t.description, '') AS description,
       coalesce(t.status, 'active') AS status
ORDER BY name
"""

# Использование атрибутов считаем отдельным запросом, а не подзапросом внутри
# RETURN: обычный MATCH поддерживается всеми версиями Neo4j 5 одинаково.
Q_TARGET_USAGE = f"""
MATCH (r:Rule)-[:APPLIES_TO]->(t:CheckTarget)
WHERE {ACTIVE.format('r')}
RETURN t.name AS name, count(r) AS rule_count
"""

Q_RULES_WITHOUT_TARGET = f"""
MATCH (r:Rule) WHERE {ACTIVE.format('r')}
  AND NOT (r)-[:APPLIES_TO]->(:CheckTarget)
RETURN elementId(r) AS nodeId, coalesce(r.ruleId, '(без ruleId)') AS label
ORDER BY label
"""

Q_MISSING_IDS = """
MATCH (n)
WHERE (n:Order       AND (n.orderId   IS NULL OR trim(toString(n.orderId))   = ''))
   OR (n:Clause      AND (n.clauseId  IS NULL OR trim(toString(n.clauseId))  = ''))
   OR (n:Rule        AND (n.ruleId    IS NULL OR trim(toString(n.ruleId))    = ''))
   OR (n:ViolationExample AND (n.exampleId IS NULL OR trim(toString(n.exampleId)) = ''))
RETURN elementId(n) AS nodeId, head(labels(n)) AS kind,
       coalesce(n.number, n.code, n.description, n.text, '(без названия)') AS label
ORDER BY kind, label
LIMIT 200
"""

Q_CLAUSES_WITHOUT_RULES = f"""
MATCH (o:Order)-[:CONTAINS]->(c:Clause)
WHERE {ACTIVE.format('o')} AND {ACTIVE.format('c')}
  AND NOT (c)-[:DEFINES]->(:Rule)
RETURN elementId(c) AS nodeId,
       coalesce(o.number, '?') + ' ' + coalesce(c.code, '?') AS label
ORDER BY label
"""

Q_ORDERS_WITHOUT_CLAUSES = f"""
MATCH (o:Order) WHERE {ACTIVE.format('o')}
  AND NOT (o)-[:CONTAINS]->(:Clause)
RETURN elementId(o) AS nodeId, coalesce(o.number, o.orderId, '?') AS label
ORDER BY label
"""

Q_EXAMPLE_COVERAGE = f"""
MATCH (r:Rule) WHERE {ACTIVE.format('r')}
OPTIONAL MATCH (r)-[:HAS_EXAMPLE]->(e:ViolationExample) WHERE {ACTIVE.format('e')}
WITH r, collect(e) AS examples
RETURN elementId(r) AS nodeId,
       coalesce(r.ruleId, '(без ruleId)') AS label,
       r.type AS type,
       size(examples) AS total,
       size([x IN examples WHERE x.isViolation = true])  AS violating,
       size([x IN examples WHERE x.isViolation = false]) AS correct
ORDER BY label
"""

Q_DUPLICATE_CODES = f"""
MATCH (o:Order)-[:CONTAINS]->(c:Clause)
WHERE {ACTIVE.format('o')} AND {ACTIVE.format('c')}
WITH o, c.code AS code, collect(elementId(c)) AS nodes
WHERE size(nodes) > 1 AND code IS NOT NULL
RETURN coalesce(o.number, '?') + ' — пункт ' + code AS label, nodes
"""

Q_ARCHIVED = """
MATCH (n)
WHERE (n:Order OR n:Clause OR n:Rule OR n:CheckTarget OR n:ViolationExample)
  AND n.status = 'archived'
RETURN head(labels(n)) AS kind, count(*) AS total
"""

KIND_NAMES = {
    "Order": "приказ", "Clause": "пункт", "Rule": "правило",
    "CheckTarget": "атрибут", "ViolationExample": "пример",
}


def _issue(code, severity, title, detail, items=None, fix=None) -> dict[str, Any]:
    return {
        "code": code, "severity": severity, "title": title, "detail": detail,
        "items": items or [], "fix": fix,
    }


# --------------------------------------------------------------------------
#  Сбор
# --------------------------------------------------------------------------


def collect() -> dict[str, Any]:
    """Полная диагностика графа."""
    issues: list[dict[str, Any]] = []

    usage = {row["name"]: row["rule_count"] for row in _run(Q_TARGET_USAGE)}
    targets = [{**row, "rule_count": usage.get(row["name"], 0)} for row in _run(Q_TARGETS)]
    active_targets = [t for t in targets if t["status"] == "active"]

    if not active_targets:
        issues.append(_issue(
            "no_check_targets", ERROR,
            "Словарь атрибутов пуст",
            "Без активных :CheckTarget агент не может извлечь из цели ничего, "
            "и любая проверка вернёт NEEDS_MANUAL_REVIEW.",
        ))

    # Двойники по написанию
    by_norm: dict[str, list[dict]] = {}
    for target in active_targets:
        by_norm.setdefault(normalize_name(target["name"] or ""), []).append(target)
    duplicates = [group for group in by_norm.values() if len(group) > 1]
    if duplicates:
        issues.append(_issue(
            "duplicate_check_targets", ERROR,
            "Атрибуты-двойники, различающиеся написанием",
            "Для Neo4j «срок исполнения» и «срок_исполнения» — разные узлы. "
            "Правило висит на одном из них, модель возвращает другое — получается "
            "ложное нарушение. Сведите двойников к одному узлу.",
            items=[{"label": " ↔ ".join(t["name"] for t in group),
                    "nodeId": group[0]["nodeId"], "kind": "CheckTarget"}
                   for group in duplicates],
        ))

    # Атрибуты без описания
    no_description = [t for t in active_targets if not t["description"].strip()]
    if no_description:
        issues.append(_issue(
            "targets_without_description", ERROR,
            "Атрибуты без описания",
            "Промпт строится из CheckTarget.description. Без него модель получает "
            "только имя, без критерия, и системно не распознаёт атрибут — правило "
            "начинает срабатывать всегда.",
            items=[{"label": t["name"], "nodeId": t["nodeId"], "kind": "CheckTarget"}
                   for t in no_description],
        ))

    # Правила без атрибутов
    rules_without_target = _run(Q_RULES_WITHOUT_TARGET)
    if rules_without_target:
        issues.append(_issue(
            "rules_without_target", ERROR,
            "Правила без привязки к атрибуту",
            "Такое правило не участвует ни в одном запросе и никогда не сработает.",
            items=[{"label": r["label"], "nodeId": r["nodeId"], "kind": "Rule"}
                   for r in rules_without_target],
        ))

    # Отсутствующие бизнес-ключи
    missing_ids = _run(Q_MISSING_IDS)
    if missing_ids:
        issues.append(_issue(
            "missing_identifiers", ERROR,
            "Узлы без идентификатора",
            "orderId / clauseId / ruleId / exampleId — ключи, по которым строится "
            "MERGE при выгрузке в seed.cypher. Без них состояние базы невозможно "
            "зафиксировать в репозитории.",
            items=[{"label": f"{KIND_NAMES.get(m['kind'], m['kind'])}: {m['label']}",
                    "nodeId": m["nodeId"], "kind": m["kind"]} for m in missing_ids],
            fix={"action": "repair_identifiers", "label": "Проставить идентификаторы"},
        ))

    # Атрибуты, на которые никто не ссылается
    orphan = [t for t in active_targets if t["rule_count"] == 0]
    if orphan:
        issues.append(_issue(
            "orphan_check_targets", WARNING,
            "Атрибуты, к которым не привязано ни одного правила",
            "Такой атрибут попадает в промпт, тратит контекст модели, но ни на что "
            "не влияет. Либо привяжите правило, либо отправьте в архив.",
            items=[{"label": t["name"], "nodeId": t["nodeId"], "kind": "CheckTarget"}
                   for t in orphan],
        ))

    # Пункты без правил и приказы без пунктов
    clauses_without_rules = _run(Q_CLAUSES_WITHOUT_RULES)
    if clauses_without_rules:
        issues.append(_issue(
            "clauses_without_rules", WARNING,
            "Пункты без правил",
            "Пункт хранит текст нормативки, но ничего не проверяет.",
            items=[{"label": c["label"], "nodeId": c["nodeId"], "kind": "Clause"}
                   for c in clauses_without_rules],
        ))

    orders_without_clauses = _run(Q_ORDERS_WITHOUT_CLAUSES)
    if orders_without_clauses:
        issues.append(_issue(
            "orders_without_clauses", WARNING,
            "Приказы без пунктов",
            "Пустой приказ ни на что не влияет.",
            items=[{"label": o["label"], "nodeId": o["nodeId"], "kind": "Order"}
                   for o in orders_without_clauses],
        ))

    # Примеры: наличие и соответствие типу правила
    coverage = _run(Q_EXAMPLE_COVERAGE)
    mismatched = [
        row for row in coverage
        if (row["type"] == "PROHIBITION" and row["violating"] == 0)
        or (row["type"] == "REQUIREMENT" and row["correct"] == 0)
    ]
    no_examples = [row for row in coverage if row["total"] == 0]
    only_mismatched = [row for row in mismatched if row["total"] > 0]

    if only_mismatched:
        issues.append(_issue(
            "example_kind_mismatch", WARNING,
            "Примеры не того вида, что нужен правилу",
            "Запрет показывает в ответе примеры с isViolation = true, требование — "
            "с isViolation = false. У этих правил примеры есть, но не те, поэтому "
            "поле examples в ответе останется пустым.",
            items=[{"label": f"{row['label']} ({row['type']})",
                    "nodeId": row["nodeId"], "kind": "Rule"} for row in only_mismatched],
        ))

    if no_examples:
        issues.append(_issue(
            "rules_without_examples", INFO,
            "Правила без примеров",
            "Примеры попадают в ответ проверки и подсказывают автору цели, "
            "как переформулировать. Без них ответ суше.",
            items=[{"label": row["label"], "nodeId": row["nodeId"], "kind": "Rule"}
                   for row in no_examples],
        ))

    # Дубли номеров пунктов внутри приказа
    duplicate_codes = _run(Q_DUPLICATE_CODES)
    if duplicate_codes:
        issues.append(_issue(
            "duplicate_clause_codes", WARNING,
            "Повторяющиеся номера пунктов",
            "В одном приказе два пункта с одинаковым номером — в ответе проверки "
            "их невозможно различить.",
            items=[{"label": row["label"], "nodeId": row["nodes"][0], "kind": "Clause"}
                   for row in duplicate_codes],
        ))

    # Справка про архив
    archived = _run(Q_ARCHIVED)
    if archived:
        issues.append(_issue(
            "archived_nodes", INFO,
            "В архиве",
            "Архивные узлы не участвуют в проверках, но остаются в графе "
            "и попадают в выгрузку seed.cypher.",
            items=[{"label": f"{KIND_NAMES.get(row['kind'], row['kind'])}: {row['total']}"}
                   for row in archived],
        ))

    errors = [i for i in issues if i["severity"] == ERROR]
    return {
        "issues": issues,
        "counts": {
            "error": len(errors),
            "warning": len([i for i in issues if i["severity"] == WARNING]),
            "info": len([i for i in issues if i["severity"] == INFO]),
        },
        "check_targets": len(active_targets),
        "ready": not errors,
        # Плоский список строк — для /ready и логов
        "problems": [f"{i['title']}: " + ", ".join(x["label"] for x in i["items"])
                     if i["items"] else i["title"] for i in errors],
    }
