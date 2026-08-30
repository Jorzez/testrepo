import os, json, re
from openai import OpenAI
from graph import get_all_attributes, find_violations

llm = OpenAI(
    base_url=os.getenv("VLLM_URL", "http://vllm:8000/v1"),
    api_key="dummy",
)
MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen3-8B")

EXTRACT_PROMPT = """Ты — классификатор целей. Дан список допустимых атрибутов:
{attrs}
Определи, какие атрибуты ПРИСУТСТВУЮТ в цели пользователя:
- "проект" — в цели явно назван проект, в рамках которого ведётся работа;
- "срок исполнения" — указана конкретная дата или период;
- "обучающий материал" — целью является изучение чего-либо или разработка обучающих материалов.
Ответь СТРОГО JSON вида: {{"attributes": ["...", "..."]}} без пояснений.
Цель: {goal}"""


def _parse_json(text: str) -> dict:
    text = re.sub(r"<think>.*?", "", text, flags=re.DOTALL)
    match = re.search(r"{.*}", text, flags=re.DOTALL)
    if not match:
        raise json.JSONDecodeError("no JSON object found", text, 0)
        return json.loads(match.group(0))


def extract_attributes(goal: str) -> list[str]:
    attrs = get_all_attributes()
    resp = llm.chat.completions.create(
    model=MODEL,
    messages=[{"role": "user",
    "content": EXTRACT_PROMPT.format(attrs=", ".join(attrs), goal=goal)}],
    temperature=0.0,
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},  # для Qwen3
    )
    try:
        data = _parse_json(resp.choices[0].message.content or "")
        return [a for a in data.get("attributes", []) if a in attrs]
    except (json.JSONDecodeError, AttributeError):
        return []


def check_goal(goal: str) -> dict:
    attributes = extract_attributes(goal)
    violations = find_violations(attributes)  # вызывать ВСЕГДА:
    # пустой список атрибутов = нарушены все требования (нет проекта, нет срока)
    return {
    "goal": goal,
    "detected_attributes": attributes,
    "allowed": len(violations) == 0,
    "violations": violations,
    }