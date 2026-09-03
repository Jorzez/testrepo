"""Тесты агента: разбор ответа модели, сопоставление имён, fail-closed."""

import pytest

import agent
from agent import (
    Extraction,
    ExtractionError,
    STATUS_ALLOWED,
    STATUS_MANUAL_REVIEW,
    STATUS_VIOLATIONS,
    build_prompt,
    check_goal,
    check_goals,
    duplicate_notes,
    extract_attributes,
    index_targets,
    normalize_name,
    parse_attributes_json,
    resolve_attributes,
)

TARGETS = [
    {"name": "срок_исполнения", "description": "указан конкретный срок"},
    {"name": "измеримость", "description": "есть числовой показатель"},
    {"name": "проект", "description": "назван проект"},
]


# --------------------------- parse_attributes_json ---------------------------


def test_parse_plain_json():
    assert parse_attributes_json('{"attributes": ["измеримость"]}') == {
        "attributes": ["измеримость"]
    }


def test_parse_strips_think_block():
    raw = '<think>рассуждаю про цель</think>\n{"attributes": ["срок_исполнения"]}'
    assert parse_attributes_json(raw)["attributes"] == ["срок_исполнения"]


def test_parse_strips_unclosed_think_block():
    raw = '{"attributes": []}\n<think>модель не закрыла тег'
    assert parse_attributes_json(raw) == {"attributes": []}


def test_parse_strips_markdown_fence():
    raw = '```json\n{"attributes": ["измеримость"]}\n```'
    assert parse_attributes_json(raw)["attributes"] == ["измеримость"]


def test_parse_handles_braces_inside_strings():
    raw = '{"attributes": ["a"], "comment": "скобка } внутри строки"}'
    assert parse_attributes_json(raw)["attributes"] == ["a"]


def test_parse_ignores_leading_prose():
    raw = 'Вот результат анализа:\n{"attributes": ["срок_исполнения"]}\nГотово.'
    assert parse_attributes_json(raw)["attributes"] == ["срок_исполнения"]


@pytest.mark.parametrize("raw", ["", "нет никакого json", "{сломанный: json", "[1, 2]"])
def test_parse_raises_on_garbage(raw):
    with pytest.raises(ExtractionError):
        parse_attributes_json(raw)


# ------------------------------ normalize_name ------------------------------


@pytest.mark.parametrize(
    "value",
    ["срок исполнения", "срок_исполнения", "Срок Исполнения", "срок-исполнения", " срок  исполнения "],
)
def test_normalize_collapses_spelling_variants(value):
    assert normalize_name(value) == "срок_исполнения"


def test_normalize_handles_yo():
    assert normalize_name("Учёт") == normalize_name("учет")


# ---------------------------- resolve_attributes ----------------------------


def test_resolve_matches_despite_spelling():
    """Модель ответила с подчёркиванием, в графе — с пробелом. Это одно и то же."""
    targets = [{"name": "срок исполнения", "description": "срок"}]
    result = resolve_attributes(["срок_исполнения"], targets)
    assert result.attributes == ["срок исполнения"]
    assert result.warnings == []


def test_resolve_expands_to_all_duplicate_variants():
    """Правила могут висеть на разных двойниках — засчитываем оба написания."""
    targets = [
        {"name": "срок исполнения", "description": ""},
        {"name": "срок_исполнения", "description": "срок"},
    ]
    result = resolve_attributes(["срок_исполнения"], targets)
    assert set(result.attributes) == {"срок исполнения", "срок_исполнения"}


def test_resolve_reports_unknown_attribute():
    result = resolve_attributes(["выдуманный_атрибут"], TARGETS)
    assert result.attributes == []
    assert result.warnings and "выдуманный_атрибут" in result.warnings[0]


def test_resolve_reports_non_string_attribute():
    result = resolve_attributes([42], TARGETS)
    assert result.attributes == []
    assert result.warnings


def test_resolve_does_not_duplicate_names():
    result = resolve_attributes(["измеримость", "Измеримость"], TARGETS)
    assert result.attributes == ["измеримость"]


# ------------------------------ index_targets -------------------------------


def test_index_groups_duplicates():
    targets = [{"name": "срок исполнения"}, {"name": "срок_исполнения"}, {"name": "проект"}]
    index = index_targets(targets)
    assert index["срок_исполнения"] == ["срок исполнения", "срок_исполнения"]
    assert index["проект"] == ["проект"]


# ------------------------------ build_prompt --------------------------------


def test_prompt_contains_all_targets_and_goal():
    prompt = build_prompt("Сдать отчёт до 01.12.2025", TARGETS)
    for t in TARGETS:
        assert t["name"] in prompt
        assert t["description"] in prompt
    assert "Сдать отчёт до 01.12.2025" in prompt


def test_prompt_lists_duplicate_only_once():
    """Два почти одинаковых варианта в списке сбивают модель с толку."""
    targets = [
        {"name": "срок_исполнения", "description": "срок"},
        {"name": "срок исполнения", "description": ""},
    ]
    prompt = build_prompt("цель", targets)
    assert prompt.count("срок") == prompt.count("срок_исполнения") + 1  # имя + описание


def test_prompt_survives_target_without_description():
    prompt = build_prompt("цель", [{"name": "проект"}])
    assert '"проект"' in prompt


# --------------------------- extract_attributes -----------------------------


class _FakeClient:
    def __init__(self, content=None, exc=None):
        outer = self

        class _Completions:
            def create(self, **kwargs):
                if exc:
                    raise exc

                class _Message:
                    pass

                message = _Message()
                message.content = content

                class _Choice:
                    pass

                choice = _Choice()
                choice.message = message

                class _Response:
                    pass

                response = _Response()
                response.choices = [choice]
                return response

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def test_extract_filters_unknown_attributes(monkeypatch):
    monkeypatch.setattr(
        agent,
        "get_client",
        lambda: _FakeClient('{"attributes": ["измеримость", "выдуманный_атрибут"]}'),
    )
    result = extract_attributes("цель", TARGETS)
    assert result.attributes == ["измеримость"]
    assert result.warnings


def test_extract_accepts_empty_list(monkeypatch):
    monkeypatch.setattr(agent, "get_client", lambda: _FakeClient('{"attributes": []}'))
    assert extract_attributes("цель", TARGETS).attributes == []


def test_extract_raises_when_dictionary_empty():
    with pytest.raises(ExtractionError):
        extract_attributes("цель", [])


def test_extract_raises_when_llm_unavailable(monkeypatch):
    monkeypatch.setattr(
        agent, "get_client", lambda: _FakeClient(exc=RuntimeError("connection refused"))
    )
    with pytest.raises(ExtractionError):
        extract_attributes("цель", TARGETS)


def test_extract_raises_on_wrong_attributes_type(monkeypatch):
    monkeypatch.setattr(
        agent, "get_client", lambda: _FakeClient('{"attributes": "измеримость"}')
    )
    with pytest.raises(ExtractionError):
        extract_attributes("цель", TARGETS)


# ------------------------------- check_goal ---------------------------------


def test_check_goal_allowed(monkeypatch):
    monkeypatch.setattr(agent, "get_check_targets", lambda: TARGETS)
    monkeypatch.setattr(
        agent, "extract_attributes", lambda goal, targets: agent.Extraction(["измеримость"])
    )
    monkeypatch.setattr(agent, "find_violations", lambda attrs: [])

    result = check_goal("цель")
    assert result["status"] == STATUS_ALLOWED
    assert result["allowed"] is True
    assert result["detected_attributes"] == ["измеримость"]
    assert result["notes"] == []


def test_check_goal_reports_violations(monkeypatch):
    violation = {"rule_id": "R-2.4", "violation_type": "MISSING_REQUIREMENT"}
    monkeypatch.setattr(agent, "get_check_targets", lambda: TARGETS)
    monkeypatch.setattr(agent, "extract_attributes", lambda g, t: agent.Extraction([]))
    monkeypatch.setattr(agent, "find_violations", lambda attrs: [violation])

    result = check_goal("цель")
    assert result["status"] == STATUS_VIOLATIONS
    assert result["allowed"] is False
    assert result["violations"] == [violation]


def test_check_goal_warns_about_duplicate_targets(monkeypatch):
    """Расхождение написаний в графе должно быть видно в ответе, а не только в логах."""
    targets = [
        {"name": "срок исполнения", "description": ""},
        {"name": "срок_исполнения", "description": "срок"},
    ]
    monkeypatch.setattr(agent, "get_check_targets", lambda: targets)
    monkeypatch.setattr(
        agent, "extract_attributes", lambda g, t: agent.Extraction(["срок_исполнения"])
    )
    monkeypatch.setattr(agent, "find_violations", lambda attrs: [])

    notes = check_goal("цель")["notes"]
    assert any("дубликаты" in n.lower() for n in notes)


def test_check_goal_passes_warnings_to_notes(monkeypatch):
    monkeypatch.setattr(agent, "get_check_targets", lambda: TARGETS)
    monkeypatch.setattr(
        agent,
        "extract_attributes",
        lambda g, t: agent.Extraction([], ["Атрибута \"X\" нет в словаре графа"]),
    )
    monkeypatch.setattr(agent, "find_violations", lambda attrs: [])

    assert check_goal("цель")["notes"] == ['Атрибута "X" нет в словаре графа']


def test_check_goal_fails_closed_on_extraction_error(monkeypatch):
    """Ключевое требование: сбой анализа НЕ должен давать allowed=True."""

    def boom(goal, targets):
        raise ExtractionError("модель недоступна")

    called = []
    monkeypatch.setattr(agent, "get_check_targets", lambda: TARGETS)
    monkeypatch.setattr(agent, "extract_attributes", boom)
    monkeypatch.setattr(agent, "find_violations", lambda attrs: called.append(attrs) or [])

    result = check_goal("цель")
    assert result["status"] == STATUS_MANUAL_REVIEW
    assert result["allowed"] is False
    assert result["notes"]
    assert called == [], "при сбое извлечения граф опрашивать не нужно"


# ------------------------------ check_goals ---------------------------------


@pytest.fixture
def bulk(monkeypatch):
    """Пакет проверяется без Neo4j и без модели."""
    calls = {"targets": 0}

    def targets():
        calls["targets"] += 1
        return TARGETS

    monkeypatch.setattr(agent, "get_check_targets", targets)
    monkeypatch.setattr(agent, "extract_attributes",
                        lambda g, t, *a: Extraction(["проект"] if "проект" in g else []))
    monkeypatch.setattr(agent, "find_violations",
                        lambda attrs: [] if "проект" in attrs else [{"attribute": "проект"}])
    return calls


def test_bulk_keeps_order_and_ids(bulk):
    result = check_goals([
        {"goal": "в рамках проекта Альфа", "id": "g-1"},
        {"goal": "просто сделать", "id": "g-2"},
    ])
    assert [r["id"] for r in result["results"]] == ["g-1", "g-2"]
    assert [r["allowed"] for r in result["results"]] == [True, False]


def test_bulk_reads_dictionary_once(bulk):
    """Словарь атрибутов — один запрос на весь пакет, а не на каждую цель."""
    check_goals([{"goal": f"цель {i}", "id": str(i)} for i in range(5)])
    assert bulk["targets"] == 1


def test_bulk_summary(bulk):
    result = check_goals([
        {"goal": "в рамках проекта", "id": "1"},
        {"goal": "без проекта", "id": "2"},
        {"goal": "тоже без", "id": "3"},
    ])
    assert result["summary"] == {"total": 3, "allowed": 1, "violations": 2, "manual_review": 0}


def test_bulk_empty_input_touches_nothing(bulk):
    result = check_goals([])
    assert result["results"] == []
    assert result["summary"]["total"] == 0
    assert bulk["targets"] == 0


def test_bulk_id_is_optional(bulk):
    assert check_goals([{"goal": "без идентификатора"}])["results"][0]["id"] is None


def test_bulk_failure_of_one_goal_does_not_break_the_batch(monkeypatch):
    def boom(goal, targets, *args):
        if "сломать" in goal:
            raise ExtractionError("модель недоступна")
        return Extraction(["проект"])

    monkeypatch.setattr(agent, "get_check_targets", lambda: TARGETS)
    monkeypatch.setattr(agent, "extract_attributes", boom)
    monkeypatch.setattr(agent, "find_violations", lambda attrs: [])

    result = check_goals([
        {"goal": "нормальная", "id": "a"},
        {"goal": "сломать", "id": "b"},
        {"goal": "снова норм", "id": "c"},
    ])
    assert [r["status"] for r in result["results"]] == [
        STATUS_ALLOWED, STATUS_MANUAL_REVIEW, STATUS_ALLOWED]
    assert result["summary"]["manual_review"] == 1


def test_duplicate_notes_computed_once_per_batch(monkeypatch):
    targets = [{"name": "срок исполнения"}, {"name": "срок_исполнения", "description": "д"}]
    monkeypatch.setattr(agent, "get_check_targets", lambda: targets)
    monkeypatch.setattr(agent, "extract_attributes", lambda g, t, *a: Extraction([]))
    monkeypatch.setattr(agent, "find_violations", lambda attrs: [])

    result = check_goals([{"goal": "a", "id": "1"}, {"goal": "b", "id": "2"}])
    for row in result["results"]:
        hits = [n for n in row["notes"] if "дубликаты" in n.lower()]
        assert len(hits) == 1, "заметка о дублях не должна повторяться внутри одной цели"


def test_duplicate_notes_helper():
    assert duplicate_notes(TARGETS) == []
    assert duplicate_notes([{"name": "срок исполнения"}, {"name": "срок_исполнения"}])
