"""Доступ к графу нормативных требований в Neo4j.

Драйвер создаётся лениво и закрывается на shutdown приложения
(см. lifespan в main.py), чтобы соединения не текли между перезапусками.
"""

import logging
import os
from typing import Any, Optional

from neo4j import Driver, GraphDatabase

log = logging.getLogger(__name__)

_driver: Optional[Driver] = None


def get_driver() -> Driver:
    """Ленивая инициализация драйвера (потокобезопасна на уровне neo4j-драйвера)."""
    global _driver
    if _driver is None:
        uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "password123")
        log.info("Инициализация драйвера Neo4j: %s", uri)
        _driver = GraphDatabase.driver(
            uri,
            auth=(user, password),
            max_connection_lifetime=3600,
            connection_acquisition_timeout=30,
        )
    return _driver


def close_driver() -> None:
    """Закрывает драйвер. Вызывается при остановке приложения."""
    global _driver
    if _driver is not None:
        log.info("Закрытие драйвера Neo4j")
        _driver.close()
        _driver = None


def verify_connectivity() -> bool:
    """Проверка доступности Neo4j. Не бросает исключений."""
    try:
        get_driver().verify_connectivity()
        return True
    except Exception as exc:  # noqa: BLE001 — здесь нужен именно широкий перехват
        log.warning("Neo4j недоступен: %s", exc)
        return False


# --------------------------------------------------------------------------
#  Cypher-запросы
# --------------------------------------------------------------------------

# Словарь проверяемых атрибутов. description идёт в промпт агента,
# поэтому единственный источник истины по атрибутам — граф, а не код.
# Архивирование — мягкое удаление: узел остаётся в графе, но выпадает из
# проверок. coalesce нужен для узлов, заведённых до появления status.
ACTIVE = "coalesce({0}.status, 'active') = 'active'"

# Разграничение по подразделениям — часть приказа, поэтому оно в графе:
#   (r:Rule)-[:ONLY_IN]->(d:Department)     правило действует только в перечисленных
#   (r:Rule)-[:EXCEPT_IN]->(d:Department)   правило в подразделении не применяется
# Правило без ONLY_IN действует для всех. $department_id = null означает
# «подразделение неизвестно»: тогда применяются все правила без изъятий.
# Ограничение ONLY_IN учитывается независимо от статуса подразделения:
# архивирование подразделения не должно молча делать правило всеобщим.
FOR_DEPARTMENT = """($department_id IS NULL
       OR NOT (r)-[:ONLY_IN]->(:Department)
       OR (r)-[:ONLY_IN]->(:Department {departmentId: $department_id}))"""

# Исключение не отбрасывает строку, а возвращается рядом с ней: агент сам
# решает, что с ним делать. Утверждённое (status = 'active') снимает
# нарушение и показывает основание, кандидат в вердикте не участвует.
EXCEPTION_MATCH = """OPTIONAL MATCH (r)-[x:EXCEPT_IN]->(:Department {departmentId: $department_id})"""
EXCEPTION_RETURN = """x.status             AS exception_status,
       x.basis              AS exception_basis,
       x.note               AS exception_note,"""

ALL_DEPARTMENTS = """
MATCH (d:Department)
WHERE d.departmentId IS NOT NULL
RETURN d.departmentId AS id, d.name AS name, coalesce(d.status, 'active') AS status
ORDER BY id
"""

ALL_CHECK_TARGETS = f"""
MATCH (t:CheckTarget)
WHERE {ACTIVE.format('t')}
RETURN t.name AS name, coalesce(t.description, '') AS description
ORDER BY name
"""

# Запрет нарушен, если атрибут ПРИСУТСТВУЕТ в цели.
FIND_PROHIBITIONS = f"""
MATCH (o:Order)-[:CONTAINS]->(c:Clause)
      -[:DEFINES]->(r:Rule)
      -[:APPLIES_TO]->(t:CheckTarget)
WHERE r.type = 'PROHIBITION'
  AND t.name IN $attributes
  AND {ACTIVE.format('o')}
  AND {ACTIVE.format('c')}
  AND {ACTIVE.format('r')}
  AND {ACTIVE.format('t')}
  AND {FOR_DEPARTMENT}
{EXCEPTION_MATCH}
OPTIONAL MATCH (r)-[:HAS_EXAMPLE]->(e:ViolationExample {{isViolation: true}})
WHERE {ACTIVE.format('e')}
RETURN o.number             AS order_number,
       o.title              AS order_title,
       c.code               AS clause_code,
       c.text               AS clause_text,
       r.ruleId             AS rule_id,
       r.description        AS rule_text,
       r.checkInstruction   AS check_instruction,
       'PROHIBITION'        AS violation_type,
       t.name               AS attribute,
       'violation'          AS example_kind,
       {EXCEPTION_RETURN}
       collect(DISTINCT e.text) AS examples
ORDER BY order_number, clause_code, rule_id, attribute
"""

# Требование нарушено, если атрибут ОТСУТСТВУЕТ в цели.
FIND_MISSING_REQUIREMENTS = f"""
MATCH (o:Order)-[:CONTAINS]->(c:Clause)
      -[:DEFINES]->(r:Rule)
      -[:APPLIES_TO]->(t:CheckTarget)
WHERE r.type = 'REQUIREMENT'
  AND NOT t.name IN $attributes
  AND {ACTIVE.format('o')}
  AND {ACTIVE.format('c')}
  AND {ACTIVE.format('r')}
  AND {ACTIVE.format('t')}
  AND {FOR_DEPARTMENT}
{EXCEPTION_MATCH}
OPTIONAL MATCH (r)-[:HAS_EXAMPLE]->(e:ViolationExample {{isViolation: false}})
WHERE {ACTIVE.format('e')}
RETURN o.number             AS order_number,
       o.title              AS order_title,
       c.code               AS clause_code,
       c.text               AS clause_text,
       r.ruleId             AS rule_id,
       r.description        AS rule_text,
       r.checkInstruction   AS check_instruction,
       'MISSING_REQUIREMENT' AS violation_type,
       t.name               AS attribute,
       'correct'            AS example_kind,
       {EXCEPTION_RETURN}
       collect(DISTINCT e.text) AS examples
ORDER BY order_number, clause_code, rule_id, attribute
"""

GRAPH_OVERVIEW = """
MATCH (n)-[r]->(m)
RETURN n, r, m
LIMIT $limit
"""

# --- Диагностика целостности словаря атрибутов ---------------------------
# Уникальность CheckTarget.name не спасает от «срок исполнения» и
# «срок_исполнения» — для базы это разные строки. Такие двойники приводят
# к ложным нарушениям, поэтому их надо видеть явно, а не по симптомам.

DUPLICATE_CHECK_TARGETS = f"""
MATCH (t:CheckTarget)
WHERE {ACTIVE.format('t')}
WITH toLower(replace(replace(trim(t.name), ' ', '_'), '-', '_')) AS norm,
     collect(t.name) AS variants
WHERE size(variants) > 1
RETURN norm, variants
ORDER BY norm
"""

CHECK_TARGETS_WITHOUT_DESCRIPTION = f"""
MATCH (t:CheckTarget)
WHERE {ACTIVE.format('t')}
  AND (t.description IS NULL OR trim(t.description) = '')
RETURN t.name AS name
ORDER BY name
"""

ORPHAN_CHECK_TARGETS = f"""
MATCH (t:CheckTarget)
WHERE {ACTIVE.format('t')}
  AND NOT (:Rule)-[:APPLIES_TO]->(t)
RETURN t.name AS name
ORDER BY name
"""

RULES_WITHOUT_TARGET = f"""
MATCH (r:Rule)
WHERE {ACTIVE.format('r')}
  AND NOT (r)-[:APPLIES_TO]->(:CheckTarget)
RETURN r.ruleId AS rule_id
ORDER BY rule_id
"""


# --------------------------------------------------------------------------
#  Публичный API модуля
# --------------------------------------------------------------------------


def get_check_targets() -> list[dict[str, str]]:
    """Словарь проверяемых атрибутов: [{'name': ..., 'description': ...}, ...]."""
    with get_driver().session() as session:
        return [dict(record) for record in session.run(ALL_CHECK_TARGETS)]


def get_all_attributes() -> list[str]:
    """Только имена атрибутов (обратная совместимость)."""
    return [t["name"] for t in get_check_targets()]


def get_departments() -> dict[str, dict[str, str]]:
    """Справочник подразделений: {departmentId: {'id', 'name', 'status'}}."""
    with get_driver().session() as session:
        return {record["id"]: dict(record) for record in session.run(ALL_DEPARTMENTS)}


def find_violations(
    attributes: list[str], department_id: Optional[str] = None
) -> list[dict[str, Any]]:
    """Все нарушения: сработавшие запреты + невыполненные требования.

    Оба набора результатов имеют одинаковый набор ключей; отличить их
    можно по violation_type и example_kind.

    department_id — подразделение, чья цель проверяется. None означает
    «неизвестно»: применяются все правила, исключения не учитываются.
    У строк, для которых в подразделении заведено исключение, заполнены
    exception_status / exception_basis / exception_note.
    """
    params = {"attributes": attributes, "department_id": department_id}
    with get_driver().session() as session:
        prohibitions = [dict(r) for r in session.run(FIND_PROHIBITIONS, **params)]
        missing = [dict(r) for r in session.run(FIND_MISSING_REQUIREMENTS, **params)]
    log.debug(
        "Найдено нарушений: запретов=%d, невыполненных требований=%d",
        len(prohibitions),
        len(missing),
    )
    return prohibitions + missing


def diagnose() -> dict[str, Any]:
    """Проверка целостности словаря атрибутов и правил.

    Возвращает найденные проблемы: дубликаты написаний, атрибуты без
    описания (модель не получит по ним критерия и будет их пропускать),
    атрибуты без правил и правила без атрибутов.
    """
    with get_driver().session() as session:
        duplicates = [dict(r) for r in session.run(DUPLICATE_CHECK_TARGETS)]
        no_description = [r["name"] for r in session.run(CHECK_TARGETS_WITHOUT_DESCRIPTION)]
        orphan_targets = [r["name"] for r in session.run(ORPHAN_CHECK_TARGETS)]
        rules_without_target = [r["rule_id"] for r in session.run(RULES_WITHOUT_TARGET)]

    problems: list[str] = []
    for row in duplicates:
        problems.append(
            "Дубликаты атрибута, различающиеся написанием: "
            + ", ".join(f'"{v}"' for v in row["variants"])
        )
    if no_description:
        problems.append(
            "Атрибуты без описания (промпт останется без критерия, модель будет "
            "их пропускать): " + ", ".join(no_description)
        )
    if orphan_targets:
        problems.append("Атрибуты, к которым не привязано ни одного правила: "
                        + ", ".join(orphan_targets))
    if rules_without_target:
        problems.append("Правила без привязки к атрибуту (никогда не сработают): "
                        + ", ".join(rules_without_target))

    return {
        "duplicate_check_targets": duplicates,
        "check_targets_without_description": no_description,
        "orphan_check_targets": orphan_targets,
        "rules_without_target": rules_without_target,
        "problems": problems,
    }
