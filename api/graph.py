import os
from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
    auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password123")),
)

# Запреты нарушены, если атрибут ПРИСУТСТВУЕТ в цели
FIND_PROHIBITIONS = """
MATCH (o:Order {status:'active'})-[:CONTAINS]->(c:Clause)
      -[:DEFINES]->(r:Rule {type:'PROHIBITION'})
      -[:APPLIES_TO]->(t:CheckTarget)
WHERE t.name IN $attributes
OPTIONAL MATCH (r)-[:HAS_EXAMPLE]->(e:ViolationExample {isViolation: true})
RETURN o.number            AS order_number,
       c.code              AS clause_code,
       c.text              AS clause_text,
       r.ruleId            AS rule_id,
       r.description       AS rule_text,
       r.checkInstruction  AS check_instruction,
       'PROHIBITION'       AS violation_type,
       t.name              AS attribute,
       collect(DISTINCT e.text) AS violation_examples
"""

# Требования нарушены, если атрибут ОТСУТСТВУЕТ в цели
FIND_MISSING_REQUIREMENTS = """
MATCH (o:Order {status:'active'})-[:CONTAINS]->(c:Clause)
      -[:DEFINES]->(r:Rule {type:'REQUIREMENT'})
      -[:APPLIES_TO]->(t:CheckTarget)
WHERE NOT t.name IN $attributes
OPTIONAL MATCH (r)-[:HAS_EXAMPLE]->(e:ViolationExample {isViolation: false})
RETURN o.number            AS order_number,
       c.code              AS clause_code,
       c.text              AS clause_text,
       r.ruleId            AS rule_id,
       r.description       AS rule_text,
       r.checkInstruction  AS check_instruction,
       'MISSING_REQUIREMENT' AS violation_type,
       t.name              AS attribute,
       collect(DISTINCT e.text) AS correct_examples
"""

ALL_ATTRIBUTES = "MATCH (t:CheckTarget) RETURN t.name AS name"


def get_all_attributes() -> list[str]:
    with driver.session() as s:
        return [rec["name"] for rec in s.run(ALL_ATTRIBUTES)]


def find_violations(attributes: list[str]) -> list[dict]:
    """Все нарушения: сработавшие запреты + невыполненные требования."""
    with driver.session() as s:
        prohibitions = [dict(r) for r in s.run(FIND_PROHIBITIONS, attributes=attributes)]
        missing = [dict(r) for r in s.run(FIND_MISSING_REQUIREMENTS, attributes=attributes)]
    return prohibitions + missing