import os, json
from openai import OpenAI
from graph import get_all_attributes, find_prohibitions

llm = OpenAI(
    base_url=os.getenv("VLLM_URL", "http://vllm:8000/v1"),
    api_key="dummy",
)
MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen3-8B")

EXTRACT_PROMPT = """Ты — классификатор целей. Дан список допустимых атрибутов:
{attrs}
Определи, какие атрибуты присутствуют в цели пользователя.
Ответь СТРОГО JSON вида: {{"attributes": ["...", "..."]}} без пояснений.
Цель: {goal}"""


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
        data = json.loads(resp.choices[0].message.content)
        return [a for a in data.get("attributes", []) if a in attrs]
    except (json.JSONDecodeError, AttributeError):
        return []


def check_goal(goal: str) -> dict:
    attributes = extract_attributes(goal)
    violations = find_prohibitions(attributes) if attributes else []
    return {
        "goal": goal,
        "detected_attributes": attributes,
        "allowed": len(violations) == 0,
        "violations": violations,
    }