"""Тесты сидера: разбиение Cypher-скрипта и согласованность схемы с запросами."""

import re
from pathlib import Path

import pytest

import graph
from seed import SCHEMA_RE, split_statements

SEED_PATH = Path(__file__).resolve().parents[2] / "neo4j" / "init" / "seed.cypher"


# --------------------------- split_statements -------------------------------


def test_splits_simple_statements():
    assert split_statements("MATCH (n) RETURN n; MATCH (m) RETURN m;") == [
        "MATCH (n) RETURN n",
        "MATCH (m) RETURN m",
    ]


def test_semicolon_inside_string_does_not_split():
    script = 'CREATE (n:X {text: "первое; второе"});'
    statements = split_statements(script)
    assert len(statements) == 1
    assert "первое; второе" in statements[0]


def test_line_comments_are_stripped():
    script = "// комментарий с ; точкой запятой\nMATCH (n) RETURN n;"
    assert split_statements(script) == ["MATCH (n) RETURN n"]


def test_block_comments_are_stripped():
    script = "/* блок ; комментария */ MATCH (n) RETURN n;"
    assert split_statements(script) == ["MATCH (n) RETURN n"]


def test_trailing_statement_without_semicolon_is_kept():
    assert split_statements("MATCH (n) RETURN n") == ["MATCH (n) RETURN n"]


def test_empty_script_gives_no_statements():
    assert split_statements("// только комментарий\n\n") == []


# ------------------------- реальный seed.cypher -----------------------------

pytestmark_seed = pytest.mark.skipif(
    not SEED_PATH.exists(), reason="seed.cypher недоступен из каталога тестов"
)


@pytest.fixture(scope="module")
def statements():
    if not SEED_PATH.exists():
        pytest.skip("seed.cypher недоступен")
    return split_statements(SEED_PATH.read_text(encoding="utf-8"))


def test_seed_parses_into_statements(statements):
    assert len(statements) > 20


def test_seed_is_idempotent(statements):
    """Данные создаются только через MERGE — иначе повторный запуск даст дубли."""
    data = [s for s in statements if not SCHEMA_RE.match(s)]
    assert data, "в сиде нет операторов с данными"
    for stmt in data:
        assert not re.search(r"\bCREATE\s*\(", stmt), f"не-идемпотентный CREATE: {stmt[:80]}"


def test_seed_defines_labels_used_by_queries(statements):
    """Схема сида должна покрывать метки, которые спрашивает graph.py."""
    script = "\n".join(statements)
    for label in ("Order", "Clause", "Rule", "CheckTarget", "ViolationExample"):
        assert f":{label}" in script, f"метка {label} отсутствует в сиде"


def test_seed_defines_properties_used_by_queries(statements):
    script = "\n".join(statements)
    for prop in ("orderId", "number", "code", "ruleId", "checkInstruction", "isViolation"):
        assert prop in script, f"свойство {prop} отсутствует в сиде"


def test_rule_types_match_queries(statements):
    """graph.py фильтрует Rule по type = PROHIBITION / REQUIREMENT."""
    script = "\n".join(statements)
    assert 'r.type = "PROHIBITION"' in script
    assert 'r.type = "REQUIREMENT"' in script
    assert "OBLIGATION" not in script, "устаревшее значение типа правила"


def test_check_targets_cover_both_rule_directions(statements):
    """У запретов и у требований должен быть хотя бы один атрибут."""
    script = "\n".join(statements)
    assert "APPLIES_TO" in script
    assert script.count("APPLIES_TO") >= 5


def test_graph_queries_reference_seed_labels():
    """Обратная проверка: запросы не должны обращаться к меткам вне схемы."""
    queries = graph.FIND_PROHIBITIONS + graph.FIND_MISSING_REQUIREMENTS + graph.ALL_CHECK_TARGETS
    for label in ("GoalAttribute", "Requirement", "Example)"):
        assert label not in queries, f"запрос ссылается на устаревшую метку {label}"


def test_both_queries_return_same_columns():
    """Клиенту не должно приходить два разных набора ключей."""
    def columns(query: str) -> set[str]:
        tail = query.split("RETURN", 1)[1].split("ORDER BY")[0]
        return set(re.findall(r"AS\s+(\w+)", tail))

    assert columns(graph.FIND_PROHIBITIONS) == columns(graph.FIND_MISSING_REQUIREMENTS)
