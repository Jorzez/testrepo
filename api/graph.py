import os
from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
    auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password123")),
)

FIND_PROHIBITIONS = """
MATCH (o:Order {status:'active'})-[:CONTAINS]->(c:Clause)
      -[:DEFINES]->(r:Rule {rule_type:'PROHIBITION'})
      -[:APPLIES_TO]->(a:GoalAttribute)
WHERE a.name IN $attributes
OPTIONAL MATCH (r)-[:HAS_EXAMPLE]->(e:Example)
OPTIONAL MATCH (r)-[:REQUIRES]->(req:Requirement)
RETURN o.order_id AS order_id, c.number AS clause_number, c.text AS clause_text,
       r.rule_id AS rule_id, r.text AS rule_text,
       collect(DISTINCT e.text) AS examples,
       collect(DISTINCT req.text) AS requirements
"""

ALL_ATTRIBUTES = "MATCH (a:GoalAttribute) RETURN a.name AS name"


def get_all_attributes() -> list[str]:
    with driver.session() as s:
        return [rec["name"] for rec in s.run(ALL_ATTRIBUTES)]


def find_prohibitions(attributes: list[str]) -> list[dict]:
    with driver.session() as s:
        return [dict(rec) for rec in s.run(FIND_PROHIBITIONS, attributes=attributes)]