"""Агент проверки формулировки цели на соответствие нормативным требованиям.

Логика:
  1. Словарь проверяемых атрибутов берётся из графа (:CheckTarget) —
     единственный источник истины, промпт строится из него же.
  2. Языковая модель определяет, какие атрибуты присутствуют в цели.
  3. Cypher-запросы находят сработавшие запреты и невыполненные требования.

Режим отказа — fail-closed: если извлечение атрибутов не удалось
(модель недоступна, вернула мусор), цель НЕ считается разрешённой,
а помечается как требующая ручной проверки.

Сопоставление имён атрибутов нечувствительно к пробелам, дефисам,
регистру и букве «ё»: расхождение в написании между ответом модели и
графом («срок исполнения» против «срок_исполнения») не должно
превращаться в ложное нарушение. О таких расхождениях и об атрибутах,
которых нет в графе, сообщается в поле notes.
"""

import json
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
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


@dataclass
class Extraction:
    """Результат извлечения атрибутов из цели."""

    attributes: list[str]
    warnings: list[str] = field(default_factory=list)


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
Копируй имена атрибутов из списка выше буква в букву, не придумывай новые
и не меняй написание. Если ни один атрибут не присутствует, верни пустой список.

Ответь строго JSON-объектом вида {{"attributes": ["имя_атрибута"]}} без пояснений.

Цель: {goal}"""


# --------------------------------------------------------------------------
#  Нормализация имён атрибутов
# --------------------------------------------------------------------------


def normalize_name(name: str) -> str:
    """Каноническая форма имени атрибута для сопоставления.

    «Срок исполнения», «срок-исполнения» и «срок_исполнения» дают один ключ.
    """
    text = str(name).replace(" ", " ").strip().lower().replace("ё", "е")
    text = re.sub(r"[\s\-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def index_targets(targets: list[dict[str, str]]) -> dict[str, list[str]]:
    """Индекс «нормализованное имя -> все написания этого атрибута в графе».

    Список значений длиннее одного означает дубликаты в графе: разные узлы
    :CheckTarget, означающие одно и то же. Правила могут висеть на разных
    из них, поэтому при совпадении засчитываются все написания сразу.
    """
    index: dict[str, list[str]] = defaultdict(list)
    for target in targets:
        index[normalize_name(target["name"])].append(target["name"])
    return dict(index)


def build_prompt(goal: str, targets: list[dict[str, str]]) -> str:
    """Собирает промпт извлечения из словаря атрибутов графа.

    Дубликаты по нормализованному имени в промпт попадают один раз:
    два почти одинаковых варианта сбивают модель с толку.
    """
    lines: list[str] = []
    seen: set[str] = set()
    for target in targets:
        key = normalize_name(target["name"])
        if key in seen:
            continue
        seen.add(key)
        description = (target.get("description") or "").strip()
        lines.append(
            f'- "{target["name"]}" — {description}' if description else f'- "{target["name"]}"'
        )
    return EXTRACT_PROMPT.format(attrs="\n".join(lines), goal=goal)


# --------------------------------------------------------------------------
#  Разбор ответа модели
# --------------------------------------------------------------------------


def _strip_reasoning(text: str) -> str:
    """Убирает блоки рассуждений и markdown-обёртки вокруг JSON."""
    text = re.sub(r"<think\b[^>]*>.*?</think\s*>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<think\b[^>]*>.*\Z", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"</?think\s*>", "", text, flags=re.IGNORECASE)
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


def resolve_attributes(
    raw_attributes: list[Any], targets: list[dict[str, str]]
) -> Extraction:
    """Сопоставляет ответ модели со словарём графа с учётом написания."""
    index = index_targets(targets)
    resolved: list[str] = []
    warnings: list[str] = []

    for item in raw_attributes:
        if not isinstance(item, str):
            warnings.append(f"Модель вернула атрибут не-строку и он отброшен: {item!r}")
            continue
        variants = index.get(normalize_name(item))
        if not variants:
            warnings.append(
                f'Атрибута "{item}" нет в словаре графа (:CheckTarget), он отброшен'
            )
            log.warning("Неизвестный атрибут от модели: %r", item)
            continue
        if item not in variants:
            # Написание разошлось, но атрибут узнан — это не повод
            # засчитывать требование невыполненным.
            log.info("Атрибут %r сопоставлен с %r по нормализованному имени", item, variants)
        for name in variants:
            if name not in resolved:
                resolved.append(name)

    return Extraction(attributes=resolved, warnings=warnings)


def extract_attributes(goal: str, targets: list[dict[str, str]]) -> Extraction:
    """Определяет присутствующие в цели атрибуты. Бросает ExtractionError при сбое."""
    if not targets:
        raise ExtractionError(
            "словарь атрибутов (:CheckTarget) пуст — граф не заполнен, "
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

    return resolve_attributes(raw_attributes, targets)


def check_goal(goal: str) -> dict[str, Any]:
    """Проверяет цель. Всегда возвращает словарь, никогда не бросает исключений LLM."""
    targets = get_check_targets()

    try:
        extraction = extract_attributes(goal, targets)
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

    violations = find_violations(extraction.attributes)

    notes = list(extraction.warnings)
    duplicates = {k: v for k, v in index_targets(targets).items() if len(v) > 1}
    if duplicates:
        # Дубликаты означают, что часть правил висит на «двойниках»
        # и результат проверки может быть неполным.
        for variants in duplicates.values():
            notes.append(
                "В графе есть дубликаты атрибута, различающиеся написанием: "
                + ", ".join(f'"{v}"' for v in variants)
                + ". Их нужно свести к одному узлу :CheckTarget."
            )

    return {
        "goal": goal,
        "status": STATUS_ALLOWED if not violations else STATUS_VIOLATIONS,
        "allowed": not violations,
        "detected_attributes": extraction.attributes,
        "violations": violations,
        "notes": notes,
    }
