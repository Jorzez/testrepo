# API

[← README](../README.md)

Полный список с интерактивными схемами — Swagger на http://localhost:8080/docs.

## Проверка целей

### Пакетная проверка

```bash
curl -s localhost:8080/check-goals \
  -H 'Content-Type: application/json' \
  -d '[{"goal": "Снизить долю просроченных заявок до 5% к 31.12.2025", "id": "kpi-1"},
       {"goal": "Улучшить работу с заявками", "id": "kpi-2"}]'
```

Вход — массив объектов `{"goal": "...", "id": "..."}`; `id` необязателен
и возвращается как передан (или `null`). Ответ:

```json
{
  "results": [ { "id": "kpi-1", "goal": "...", "status": "...", "allowed": true,
                 "detected_attributes": [], "violations": [], "notes": [] } ],
  "summary": { "total": 2, "allowed": 1, "violations": 1, "manual_review": 0 }
}
```

Порядок ответов совпадает с порядком входа. Словарь атрибутов читается один
раз на весь пакет, обращения к модели идут параллельно (`BULK_MAX_WORKERS`,
по умолчанию 4) — узкое место именно они. Сбой одной цели не роняет пакет:
она получает `NEEDS_MANUAL_REVIEW`, остальные проверяются как обычно.
Размер пакета ограничен `MAX_GOALS_PER_REQUEST` (по умолчанию 200), при
превышении — `413`.

### Прочее

```bash
curl -s localhost:8080/health          # liveness
curl -s localhost:8080/ready           # readiness + диагностика графа
curl -s localhost:8080/check-targets   # словарь проверяемых атрибутов

curl -s localhost:8080/check-goal \
  -H 'Content-Type: application/json' \
  -d '{"goal": "Снизить долю просроченных заявок до 5% к 31.12.2025"}'
```

`/ready` отдаёт 503 и список `problems`, если Neo4j недоступен, граф пуст,
есть двойники атрибутов, атрибуты без описания, атрибуты без правил или
правила без атрибутов — то есть в любой ситуации, когда проверка целей
будет молча неполной. Разбор каждой проверки — в [диагностике](web-ui.md#диагностика).

Ответ `/check-goal`:

```json
{
  "goal": "...",
  "status": "ALLOWED | VIOLATIONS_FOUND | NEEDS_MANUAL_REVIEW",
  "allowed": false,
  "detected_attributes": ["срок_исполнения", "измеримость"],
  "violations": [
    {
      "order_number": "ПР-01",
      "order_title": "О порядке постановки целей",
      "clause_code": "1.1",
      "clause_text": "...",
      "rule_id": "R-1.1",
      "rule_text": "...",
      "check_instruction": "Проверь, указан ли в тексте цели проект...",
      "violation_type": "MISSING_REQUIREMENT",
      "attribute": "проект",
      "example_kind": "correct",
      "examples": ["..."]
    }
  ],
  "notes": []
}
```

`notes` — не декоративное поле. Туда попадают атрибуты, которых нет
в словаре графа, и обнаруженные двойники написаний: это причины, по
которым результат проверки может быть неполным.

Оба типа нарушений возвращаются с одинаковым набором полей; различать их
следует по `violation_type` и `example_kind` (`violation` — так делать нельзя,
`correct` — образец правильной формулировки).

### Режим отказа: fail-closed

Если извлечь атрибуты не удалось (модель недоступна, вернула не JSON,
словарь `CheckTarget` пуст), ответ будет `status: NEEDS_MANUAL_REVIEW`
и `allowed: false`, а причина — в `notes`. Проверка соответствия
никогда не «разрешает» цель из-за собственного сбоя.

## Эндпоинты каталога

```
GET    /catalog/tree?include_archived=false     всё дерево одним ответом
GET    /catalog/check-targets                   словарь атрибутов
GET    /catalog/clauses                         плоский список пунктов
GET    /catalog/diagnostics                     развёрнутая диагностика

GET    /catalog/nodes/{nodeId}                  все свойства узла
PATCH  /catalog/nodes/{nodeId}/properties       правка любых свойств (null удаляет)
POST   /catalog/nodes/{nodeId}/status           active / archived
GET    /catalog/nodes/{nodeId}/descendants      что уйдёт при удалении
DELETE /catalog/nodes/{nodeId}                  физическое удаление

POST   /catalog/orders                          POST /catalog/clauses
POST   /catalog/rules                           POST /catalog/examples
POST   /catalog/check-targets

PUT    /catalog/rules/{nodeId}/targets          привязка правила к атрибутам
PUT    /catalog/clauses/{nodeId}/references     перекрёстные ссылки
POST   /catalog/clauses/{nodeId}/move           перенос в другой приказ
POST   /catalog/rules/{nodeId}/move             перенос в другой пункт
POST   /catalog/repair-identifiers              проставить недостающие ключи

DELETE /catalog/nodes/{nodeId}?force=true       удалить без архивирования
```

`404` — узла нет, `409` — операция противоречит состоянию графа
(двойник по написанию, удаление неархивированного узла, используемый атрибут,
занятый бизнес-ключ), `422` — не прошла валидация схемы.
