# API

[← README](../README.md)

Полный список с интерактивными схемами — Swagger на http://localhost:8080/docs
(выключен по умолчанию, включается `ENABLE_DOCS=1`).

## Вход

Все маршруты, кроме `/health`, `/ready` и входа, требуют сессию. Снаружи
API доступен под `/api` интерфейса; порт 8080 слушает только сам сервер.

```bash
# Вход: cookie сессии сохраняется в файл. Пароль лучше не оставлять в истории оболочки.
curl -s -c cookies.txt https://<интерфейс>/api/auth/login \
  -H 'X-Requested-With: XMLHttpRequest' -H 'Content-Type: application/json' \
  -d '{"login": "i.ivanov", "password": "…"}'

curl -s -b cookies.txt https://<интерфейс>/api/check-goal \
  -H 'X-Requested-With: XMLHttpRequest' -H 'Content-Type: application/json' \
  -d '{"goal": "Снизить долю просроченных заявок до 5% к 31.12.2025", "department_id": "UCT"}'
```

```
POST   /auth/login                {login, password} → {login, role, displayName}, ставит cookie
POST   /auth/logout               закрывает сессию
GET    /auth/me                   кто вошёл

GET    /auth/users                реестр пользователей            (администратор)
POST   /auth/users                {login, role, displayName}      (администратор)
PATCH  /auth/users/{login}        {role, status, displayName}     (администратор)
DELETE /auth/users/{login}                                        (администратор)
```

Изменяющие запросы (`POST`, `PUT`, `PATCH`, `DELETE`) обязаны нести заголовок
`X-Requested-With: XMLHttpRequest` — без него ответ `403`. Чтение каталога
и проверка целей доступны любой роли, правка — редактору, физическое
удаление, `repair-identifiers` и `/auth/users` — администратору;
см. [роли](security.md#роли).

## Проверка целей

### Пакетная проверка

```bash
curl -s -b cookies.txt https://<интерфейс>/api/check-goals \
  -H 'X-Requested-With: XMLHttpRequest' -H 'Content-Type: application/json' \
  -d '[{"goal": "Снизить долю просроченных заявок до 5% к 31.12.2025", "department_id": "UCT", "id": "kpi-1"},
       {"goal": "Улучшить работу с заявками", "department_id": "AGD", "id": "kpi-2"}]'
```

Вход — массив объектов `{"goal": "...", "department_id": "...", "id": "..."}`.

| Поле | Обязательно | Назначение |
|---|---|---|
| `goal` | да | формулировка цели |
| `department_id` | да | `departmentId` подразделения, чья это цель; без поля или с пустой строкой запрос отклоняется с `422` |
| `id` | нет | идентификатор вызывающей системы, возвращается как передан (или `null`) |

Идентификатор, которого нет в графе, пакет не роняет: цель проверяется
по всем правилам, а причина пишется в её `notes` — см.
[разграничение по подразделениям](architecture.md#разграничение-по-подразделениям).

Ответ:

```json
{
  "results": [ { "id": "kpi-1", "goal": "...", "status": "...", "allowed": true,
                 "department": {"id": "UCT", "name": "УЦТ"},
                 "detected_attributes": [], "violations": [], "exemptions": [], "notes": [] } ],
  "summary": { "total": 2, "allowed": 1, "violations": 1, "manual_review": 0 }
}
```

Порядок ответов совпадает с порядком входа. Словари атрибутов и подразделений
читаются один раз на весь пакет, обращения к модели идут параллельно (`BULK_MAX_WORKERS`,
по умолчанию 4) — узкое место именно они. Сбой одной цели не роняет пакет:
она получает `NEEDS_MANUAL_REVIEW`, остальные проверяются как обычно.
Размер пакета ограничен `MAX_GOALS_PER_REQUEST` (по умолчанию 200), при
превышении — `413`.

### Прочее

```bash
curl -s localhost:8080/health          # liveness, без входа
curl -s localhost:8080/ready           # readiness + диагностика графа, без входа, только с сервера
```

`GET /check-targets` — словарь проверяемых атрибутов, `POST /check-goal` —
одна цель (пример — в разделе «Вход»).

В одиночной проверке `department_id` необязателен: без него применяются
все правила, а в `notes` появляется причина.

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
  "department": {"id": "UCT", "name": "УЦТ"},
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
      "examples": ["..."],
      "candidate_exception": null
    }
  ],
  "exemptions": [
    {
      "order_number": "ПР-01",
      "clause_code": "2.4",
      "rule_id": "R-2.4",
      "violation_type": "MISSING_REQUIREMENT",
      "attribute": "срок_исполнения",
      "basis": "ПР-01 п. 2.5",
      "note": null
    }
  ],
  "notes": []
}
```

Поля, связанные с подразделением:

| Поле | Что в нём |
|---|---|
| `department` | найденное подразделение или `null`, если оно не передано, неизвестно графу или в архиве — тогда применены все правила, причина в `notes` |
| `exemptions` | нарушения, снятые утверждённым исключением для этого подразделения. Набор полей как у нарушения, плюс `basis` — пункт приказа, который вводит исключение, и `note`. На `status` и `allowed` не влияют |
| `violations[].candidate_exception` | `{basis, note}`, если для подразделения есть исключение-кандидат. Оно не утверждено, поэтому нарушение остаётся; поле показывает проверяющему, что договорённость ждёт решения. Иначе `null` |

`notes` — не декоративное поле. Туда попадают атрибуты, которых нет
в словаре графа, обнаруженные двойники написаний и неопределённое
подразделение: это причины, по которым результат проверки может быть
неполным или строже ожидаемого.

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
GET    /catalog/departments?include_archived=false   подразделения и их правила
GET    /catalog/diagnostics                     развёрнутая диагностика

GET    /catalog/nodes/{nodeId}                  все свойства узла
PATCH  /catalog/nodes/{nodeId}/properties       правка любых свойств (null удаляет)
POST   /catalog/nodes/{nodeId}/status           active / archived
GET    /catalog/nodes/{nodeId}/descendants      что уйдёт при удалении
DELETE /catalog/nodes/{nodeId}                  физическое удаление

POST   /catalog/orders                          POST /catalog/clauses
POST   /catalog/rules                           POST /catalog/examples
POST   /catalog/check-targets                   POST /catalog/departments

PUT    /catalog/rules/{nodeId}/targets          привязка правила к атрибутам
PUT    /catalog/rules/{nodeId}/departments      область действия: «только в» и исключения
PUT    /catalog/clauses/{nodeId}/references     перекрёстные ссылки
POST   /catalog/clauses/{nodeId}/move           перенос в другой приказ
POST   /catalog/rules/{nodeId}/move             перенос в другой пункт
POST   /catalog/repair-identifiers              проставить недостающие ключи

DELETE /catalog/nodes/{nodeId}?force=true       удалить без архивирования
```

Тело `PUT /catalog/rules/{nodeId}/departments` заменяет область действия целиком:

```json
{
  "only": ["UCT", "AGD"],
  "exceptions": [
    {"departmentId": "AGD", "status": "active", "basis": "ПР-01 п. 2.5"},
    {"departmentId": "UCT", "status": "candidate", "note": "договорённость отдела"}
  ]
}
```

Пустые списки — правило действует для всех. `status` по умолчанию `candidate`;
для `active` обязателен `basis`. Если `only` задан, исключения допустимы
только внутри него («действует в УЦТ и АГД, но в АГД — исключение по п. 2.5»):
вне списка правило и так не действует.

`401` — нет сессии или она истекла, `403` — не хватает роли либо нет
заголовка `X-Requested-With`, `429` — слишком много неудачных входов,
`404` — узла нет, `409` — операция противоречит состоянию графа
(двойник по написанию, удаление неархивированного узла, используемый атрибут
или подразделение, занятый бизнес-ключ, действующее исключение без основания),
`422` — не прошла валидация схемы.
