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
ALL_CHECK_TARGETS = """
MATCH (t:CheckTarget)
RETURN t.name AS name, coalesce(t.description, '') AS description
ORDER BY name
"""

# Запрет нарушен, если атрибут ПРИСУТСТВУЕТ в цели.
FIND_PROHIBITIONS = """
MATCH (o:Order {status: 'active'})-[:CONTAINS]->(c:Clause)
      -[:DEFINES]->(r:Rule {type: 'PROHIBITION'})
      -[:APPLIES_TO]->(t:CheckTarget)
WHERE t.name IN $attributes
OPTIONAL MATCH (r)-[:HAS_EXAMPLE]->(e:ViolationExample {isViolation: true})
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
       collect(DISTINCT e.text) AS examples
ORDER BY order_number, clause_code, rule_id, attribute
"""

# Требование нарушено, если атрибут ОТСУТСТВУЕТ в цели.
FIND_MISSING_REQUIREMENTS = """
MATCH (o:Order {status: 'active'})-[:CONTAINS]->(c:Clause)
      -[:DEFINES]->(r:Rule {type: 'REQUIREMENT'})
      -[:APPLIES_TO]->(t:CheckTarget)
WHERE NOT t.name IN $attributes
OPTIONAL MATCH (r)-[:HAS_EXAMPLE]->(e:ViolationExample {isViolation: false})
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
       collect(DISTINCT e.text) AS examples
ORDER BY order_number, clause_code, rule_id, attribute
"""

GRAPH_OVERVIEW = """
MATCH (n)-[r]->(m)
RETURN n, r, m
LIMIT $limit
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


def find_violations(attributes: list[str]) -> list[dict[str, Any]]:
    """Все нарушения: сработавшие запреты + невыполненные требования.

    Оба набора результатов имеют одинаковый набор ключей; отличить их
    можно по violation_type и example_kind.
    """
    with get_driver().session() as session:
        prohibitions = [
            dict(r) for r in session.run(FIND_PROHIBITIONS, attributes=attributes)
        ]
        missing = [
            dict(r)
            for r in session.run(FIND_MISSING_REQUIREMENTS, attributes=attributes)
        ]
    log.debug(
        "Найдено нарушений: запретов=%d, невыполненных требований=%d",
        len(prohibitions),
        len(missing),
    )
    return prohibitions + missing
