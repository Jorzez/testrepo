"""Тесты агента: разбор ответа модели, фильтрация атрибутов, fail-closed."""

import pytest

import agent
from agent import (
    ExtractionError,
    STATUS_ALLOWED,
    STATUS_MANUAL_REVIEW,
    STATUS_VIOLATIONS,
    build_prompt,
    check_goal,
    extract_attributes,
    parse_attributes_json,
)

TARGETS = [
    {"name": "срок_исполнения", "description": "указан конкретный срок"},
    {"name": "измеримость", "description": "есть числовой показатель"},
    {"name": "персональные_данные", "description": "упомянут конкретный человек"},
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
    """Незакрытый <think> не должен съедать JSON и не должен ломать разбор."""
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


# ------------------------------ build_prompt --------------------------------


def test_prompt_contains_all_targets_and_goal():
    prompt = build_prompt("Сдать отчёт до 01.12.2025", TARGETS)
    for t in TARGETS:
        assert t["name"] in prompt
        assert t["description"] in prompt
    assert "Сдать отчёт до 01.12.2025" in prompt


# --------------------------- extract_attributes -----------------------------


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


def _fake_client(content=None, exc=None):
    class _Completions:
        def create(self, **kwargs):
            if exc:
                raise exc
            return _FakeResponse(content)

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    return _Client()


def test_extract_filters_unknown_attributes(monkeypatch):
    monkeypatch.setattr(
        agent,
        "get_client",
        lambda: _fake_client('{"attributes": ["измеримость", "выдуманный_атрибут"]}'),
    )
    assert extract_attributes("цель", TARGETS) == ["измеримость"]


def test_extract_accepts_empty_list(monkeypatch):
    monkeypatch.setattr(agent, "get_client", lambda: _fake_client('{"attributes": []}'))
    assert extract_attributes("цель", TARGETS) == []


def test_extract_raises_when_dictionary_empty():
    with pytest.raises(ExtractionError):
        extract_attributes("цель", [])


def test_extract_raises_when_llm_unavailable(monkeypatch):
    monkeypatch.setattr(
        agent, "get_client", lambda: _fake_client(exc=RuntimeError("connection refused"))
    )
    with pytest.raises(ExtractionError):
        extract_attributes("цель", TARGETS)


def test_extract_raises_on_wrong_attributes_type(monkeypatch):
    monkeypatch.setattr(
        agent, "get_client", lambda: _fake_client('{"attributes": "измеримость"}')
    )
    with pytest.raises(ExtractionError):
        extract_attributes("цель", TARGETS)


# ------------------------------- check_goal ---------------------------------


def test_check_goal_allowed(monkeypatch):
    monkeypatch.setattr(agent, "get_check_targets", lambda: TARGETS)
    monkeypatch.setattr(agent, "extract_attributes", lambda goal, targets: ["измеримость"])
    monkeypatch.setattr(agent, "find_violations", lambda attrs: [])

    result = check_goal("цель")
    assert result["status"] == STATUS_ALLOWED
    assert result["allowed"] is True
    assert result["detected_attributes"] == ["измеримость"]


def test_check_goal_reports_violations(monkeypatch):
    violation = {"rule_id": "R-002", "violation_type": "MISSING_REQUIREMENT"}
    monkeypatch.setattr(agent, "get_check_targets", lambda: TARGETS)
    monkeypatch.setattr(agent, "extract_attributes", lambda goal, targets: [])
    monkeypatch.setattr(agent, "find_violations", lambda attrs: [violation])

    result = check_goal("цель")
    assert result["status"] == STATUS_VIOLATIONS
    assert result["allowed"] is False
    assert result["violations"] == [violation]


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
