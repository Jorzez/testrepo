# Goal Checker Agent

Проверка формулировки цели на соответствие действующим приказам.
Требования хранятся графом в Neo4j, языковая модель (vLLM) определяет,
какие проверяемые атрибуты присутствуют в тексте цели, Cypher-запросы
находят сработавшие запреты и невыполненные требования.

## Архитектура

```
web (nginx :3000) ──► визуализация графа (neovis.js) ──► Neo4j :7687
api (FastAPI :8080) ─┬─► Neo4j :7687      поиск нарушений
                     └─► vLLM :8000       извлечение атрибутов из цели
seeder (разовый)   ──► Neo4j              загрузка neo4j/init/seed.cypher
```

## Модель данных

```
(:Order {orderId, number, title, date, status})
  -[:CONTAINS]->   (:Clause {clauseId, code, text})
  -[:DEFINES]->    (:Rule {ruleId, type, description, checkInstruction})
  -[:APPLIES_TO]-> (:CheckTarget {name, description})

(:Rule)-[:HAS_EXAMPLE]->(:ViolationExample {exampleId, text, isViolation})
(:Clause)-[:REFERENCES]->(:Clause)
```

`Rule.type` задаёт направление проверки:

| type | Нарушение возникает, когда атрибут |
|---|---|
| `PROHIBITION` | **присутствует** в цели |
| `REQUIREMENT` | **отсутствует** в цели |

`CheckTarget` — единственный источник истины по проверяемым атрибутам.
Промпт для модели строится из `CheckTarget.description` во время выполнения,
поэтому новый атрибут добавляется правкой `seed.cypher`, а не кода.

## Запуск

В `.env` должны быть заданы `NEO4J_PASSWORD`, `VLLM_MODEL` и `HF_TOKEN`
(полный список — в таблице ниже).

```bash
docker compose up -d --build
```

Порядок подъёма задан через `depends_on`: `neo4j` → `seeder` → `api`.
API стартует только после того, как сидер успешно отработал, а vLLM
прошёл healthcheck (загрузка весов 8B-модели занимает несколько минут,
поэтому у неё `start_period: 900s`).

| Сервис | Адрес |
|---|---|
| API | http://localhost:8080 |
| Swagger | http://localhost:8080/docs |
| Визуализация графа | http://localhost:3000 |
| Neo4j Browser | http://localhost:7474 |

Для запуска без GPU укажите внешний OpenAI-совместимый эндпоинт
через `VLLM_URL` и поднимайте стек без сервиса `vllm`.

## Эндпоинты

```bash
curl -s localhost:8080/health          # liveness
curl -s localhost:8080/ready           # readiness: Neo4j + заполненность графа
curl -s localhost:8080/check-targets   # словарь проверяемых атрибутов

curl -s localhost:8080/check-goal \
  -H 'Content-Type: application/json' \
  -d '{"goal": "Снизить долю просроченных заявок до 5% к 31.12.2025"}'
```

Ответ `/check-goal`:

```json
{
  "goal": "...",
  "status": "ALLOWED | VIOLATIONS_FOUND | NEEDS_MANUAL_REVIEW",
  "allowed": false,
  "detected_attributes": ["срок_исполнения"],
  "violations": [
    {
      "order_number": "ПР-2024-15",
      "order_title": "...",
      "clause_code": "п. 3.2",
      "clause_text": "...",
      "rule_id": "R-002",
      "rule_text": "...",
      "check_instruction": "Добавьте в формулировку числовой показатель...",
      "violation_type": "MISSING_REQUIREMENT",
      "attribute": "измеримость",
      "example_kind": "correct",
      "examples": ["..."]
    }
  ],
  "notes": []
}
```

Оба типа нарушений возвращаются с одинаковым набором полей; различать их
следует по `violation_type` и `example_kind` (`violation` — так делать нельзя,
`correct` — образец правильной формулировки).

### Режим отказа: fail-closed

Если извлечь атрибуты не удалось (модель недоступна, вернула не JSON,
словарь `CheckTarget` пуст), ответ будет `status: NEEDS_MANUAL_REVIEW`
и `allowed: false`, а причина — в `notes`. Проверка соответствия
никогда не «разрешает» цель из-за собственного сбоя.

## Загрузка данных

`neo4j/init/seed.cypher` идемпотентен: схема создаётся через
`IF NOT EXISTS`, данные — через `MERGE`, поэтому сидер безопасно
запускается при каждом подъёме стека.

Перезалить граф вручную:

```bash
docker compose run --rm seeder
```

## Тесты

```bash
cd api
pip install -r requirements-dev.txt
pytest
```

Тесты не требуют ни Neo4j, ни vLLM — внешние зависимости подменяются.
Покрыты: разбор ответа модели (блоки `<think>`, markdown-ограждения,
мусор), фильтрация неизвестных атрибутов, поведение fail-closed,
разбиение Cypher-скрипта и согласованность `seed.cypher` с запросами
в `graph.py` — то есть ровно те места, где расхождение схемы и кода
уже приводило к молчаливым отказам.

## Переменные окружения

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `NEO4J_PASSWORD` | — | пароль Neo4j (обязательна) |
| `VLLM_MODEL` | — | имя модели для vLLM |
| `HF_TOKEN` | — | токен Hugging Face для загрузки весов |
| `VLLM_IMAGE` | `vllm/vllm-openai:latest` | образ vLLM, рекомендуется зафиксировать тег |
| `VLLM_URL` | `http://vllm:8000/v1` | адрес OpenAI-совместимого API |
| `LLM_TIMEOUT_SECONDS` | `60` | таймаут запроса к модели |
| `LLM_MAX_RETRIES` | `2` | число повторов запроса к модели |
| `CORS_ORIGINS` | `http://localhost:3000` | разрешённые источники, через запятую |
| `LOG_LEVEL` | `INFO` | уровень логирования |

## Известные ограничения

- Пароль Neo4j передаётся в браузер в `web/index.html`: neovis.js ходит
  в базу напрямую по bolt. Для публичного развёртывания запросы графа
  нужно проксировать через API.
- `/check-goal` не аутентифицирован и не ограничен по частоте и длине входа.
- Текст цели попадает в промпт без экранирования — возможна prompt injection.
- Версии Python-зависимостей зафиксированы вручную; для полной
  воспроизводимости стоит перейти на lock-файл (`pip-compile`, `uv lock`).
