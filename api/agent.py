"""Агент проверки формулировки цели на соответствие нормативным требованиям.

Логика:
  1. Словарь проверяемых атрибутов берётся из графа (:CheckTarget) —
     единственный источник истины, промпт строится из него же.
  2. Языковая модель определяет, какие атрибуты присутствуют в цели.
  3. Cypher-запросы находят сработавшие запреты и невыполненные требования.

Режим отказа — fail-closed: если извлечение атрибутов не удалось
(модель недоступна, вернула мусор), цель НЕ считается разрешённой,
а помечается как требующая ручной проверки.
"""

import json
import logging
import os
import re
from typing import Any, Optional

from openai import OpenAI

from graph import find_violations, get_check_targets

log = logging.getLogger(__name__)

MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen3-8B")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))

# Статусы результата проверки
STATUS_ALLOWED = "ALLOWED"
STATUS_VIOLATIONS = "VIOLATIONS_FOUND"
STATUS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"

_client: Optional[OpenAI] = None


class ExtractionError(RuntimeError):
    """Не удалось получить от модели список атрибутов."""


def get_client() -> OpenAI:
    """Ленивая инициализация клиента vLLM (OpenAI-совместимый API)."""
    global _client
    if _client is None:
        base_url = os.getenv("VLLM_URL", "http://vllm:8000/v1")
        log.info("Инициализация клиента LLM: %s (модель %s)", base_url, MODEL)
        _client = OpenAI(
            base_url=base_url,
            api_key=os.getenv("VLLM_API_KEY", "dummy"),
            timeout=LLM_TIMEOUT,
            max_retries=LLM_MAX_RETRIES,
        )
    return _client


EXTRACT_PROMPT = """Ты — классификатор формулировок целей.

Ниже перечислены проверяемые атрибуты и условия, при которых атрибут
считается присутствующим в цели:
{attrs}

Определи, какие из перечисленных атрибутов присутствуют в цели пользователя.
Используй ТОЛЬКО имена атрибутов из списка выше, не придумывай новые.
Если ни один атрибут не присутствует, верни пустой список.

Ответь строго JSON-объектом вида {{"attributes": ["имя_атрибута"]}} без пояснений.

Цель: {goal}"""


def build_prompt(goal: str, targets: list[dict[str, str]]) -> str:
    """Собирает промпт извлечения из словаря атрибутов графа."""
    lines = [
        f'- "{t["name"]}" — {t["description"]}' if t.get("description") else f'- "{t["name"]}"'
        for t in targets
    ]
    return EXTRACT_PROMPT.format(attrs="\n".join(lines), goal=goal)


def _strip_reasoning(text: str) -> str:
    """Убирает блоки рассуждений и markdown-обёртки вокруг JSON."""
    # Полные и незакрытые блоки <think>...</think> (Qwen3 и подобные)
    text = re.sub(r"<think\b[^>]*>.*?</think\s*>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<think\b[^>]*>.*\Z", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"</?think\s*>", "", text, flags=re.IGNORECASE)
    # Ограждения ```json ... ```
    text = re.sub(r"```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = text.replace("```", "")
    return text.strip()


def _first_json_object(text: str) -> str:
    """Возвращает первый сбалансированный по скобкам JSON-объект в тексте."""
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth:
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    raise ValueError("в ответе модели нет сбалансированного JSON-объекта")


def parse_attributes_json(text: str) -> dict[str, Any]:
    """Извлекает JSON-объект из свободного ответа модели.

    Бросает ExtractionError, если разобрать ответ не удалось.
    """
    cleaned = _strip_reasoning(text or "")
    try:
        raw = _first_json_object(cleaned)
    except ValueError as exc:
        raise ExtractionError(str(exc)) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"невалидный JSON в ответе модели: {exc}") from exc
    if not isinstance(data, dict):
        raise ExtractionError("ожидался JSON-объект, получен другой тип")
    return data


def extract_attributes(goal: str, targets: list[dict[str, str]]) -> list[str]:
    """Определяет присутствующие в цели атрибуты. Бросает ExtractionError при сбое."""
    allowed = {t["name"] for t in targets}
    if not allowed:
        raise ExtractionError(
            "словарь атрибутов (:CheckTarget) пуст — база не заполнена, "
            "запустите сервис seeder"
        )

    try:
        response = get_client().chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": build_prompt(goal, targets)}],
            temperature=0.0,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},  # Qwen3
        )
    except Exception as exc:  # noqa: BLE001 — любой сбой LLM переводим в ExtractionError
        log.exception("Вызов LLM завершился ошибкой")
        raise ExtractionError(f"модель недоступна: {exc}") from exc

    content = response.choices[0].message.content if response.choices else ""
    log.debug("Сырой ответ модели: %s", content)

    data = parse_attributes_json(content or "")
    raw_attributes = data.get("attributes")
    if not isinstance(raw_attributes, list):
        log.warning("Модель вернула attributes неверного типа: %r", raw_attributes)
        raise ExtractionError("поле attributes отсутствует или не является списком")

    known = [a for a in raw_attributes if isinstance(a, str) and a in allowed]
    unknown = [a for a in raw_attributes if a not in allowed]
    if unknown:
        log.warning("Модель вернула неизвестные атрибуты, они отброшены: %r", unknown)
    return known


def check_goal(goal: str) -> dict[str, Any]:
    """Проверяет цель. Всегда возвращает словарь, никогда не бросает исключений LLM."""
    targets = get_check_targets()

    try:
        attributes = extract_attributes(goal, targets)
    except ExtractionError as exc:
        # fail-closed: не подтверждаем соответствие, если не смогли разобрать цель
        log.error("Извлечение атрибутов не удалось: %s", exc)
        return {
            "goal": goal,
            "status": STATUS_MANUAL_REVIEW,
            "allowed": False,
            "detected_attributes": [],
            "violations": [],
            "notes": [
                "Не удалось автоматически проанализировать формулировку цели. "
                "Требуется ручная проверка.",
                str(exc),
            ],
        }

    violations = find_violations(attributes)
    return {
        "goal": goal,
        "status": STATUS_ALLOWED if not violations else STATUS_VIOLATIONS,
        "allowed": not violations,
        "detected_attributes": attributes,
        "violations": violations,
        "notes": [],
    }
