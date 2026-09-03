// ============================================================
//  Граф нормативных требований к формулировке целей
//
//  Схема (совпадает с запросами в api/graph.py):
//    (:Order   {orderId, number, title, date, status})
//      -[:CONTAINS]->   (:Clause {clauseId, code, text})
//      -[:DEFINES]->    (:Rule   {ruleId, type, description, checkInstruction})
//      -[:APPLIES_TO]-> (:CheckTarget {name, description})
//    (:Rule)-[:HAS_EXAMPLE]->(:ViolationExample {exampleId, text, isViolation})
//    (:Clause)-[:REFERENCES]->(:Clause)
//
//  Rule.type:
//    PROHIBITION — нарушение, если атрибут ПРИСУТСТВУЕТ в цели
//    REQUIREMENT — нарушение, если атрибут ОТСУТСТВУЕТ в цели
//
//  Скрипт идемпотентен: повторный запуск не создаёт дублей.
// ============================================================

// ---------- Ограничения и индексы ----------
CREATE CONSTRAINT order_id IF NOT EXISTS
FOR (o:Order) REQUIRE o.orderId IS UNIQUE;

CREATE CONSTRAINT clause_id IF NOT EXISTS
FOR (c:Clause) REQUIRE c.clauseId IS UNIQUE;

CREATE CONSTRAINT rule_id IF NOT EXISTS
FOR (r:Rule) REQUIRE r.ruleId IS UNIQUE;

CREATE CONSTRAINT check_target_name IF NOT EXISTS
FOR (t:CheckTarget) REQUIRE t.name IS UNIQUE;

CREATE CONSTRAINT example_id IF NOT EXISTS
FOR (e:ViolationExample) REQUIRE e.exampleId IS UNIQUE;

CREATE FULLTEXT INDEX rule_description_ft IF NOT EXISTS
FOR (r:Rule) ON EACH [r.description];

// ---------- Приказы ----------
MERGE (o:Order {orderId: "PR-2024-15"})
SET o.number = "ПР-2024-15",
    o.title  = "Об утверждении требований к формулировке целей",
    o.date   = date("2024-03-01"),
    o.status = "active";

MERGE (o:Order {orderId: "PR-2024-22"})
SET o.number = "ПР-2024-22",
    o.title  = "О безопасности при постановке задач",
    o.date   = date("2024-06-10"),
    o.status = "active";

// ---------- Атрибуты цели (словарь CheckTarget) ----------
// description используется агентом для построения промпта извлечения,
// поэтому формулировки должны быть понятны языковой модели.

MERGE (t:CheckTarget {name: "персональные_данные"})
SET t.description = "в тексте цели упомянуты персональные данные конкретного человека: ФИО или фамилия с инициалами, номер телефона, адрес, паспортные данные, табельный номер";

MERGE (t:CheckTarget {name: "измеримость"})
SET t.description = "в цели есть измеримый показатель результата: число, процент, количество, объём или иной проверяемый критерий выполнения";

MERGE (t:CheckTarget {name: "срок_исполнения"})
SET t.description = "в цели указан конкретный срок: дата, месяц, квартал, год или явный период выполнения";

MERGE (t:CheckTarget {name: "срок_свыше_12_месяцев_без_этапов"})
SET t.description = "срок цели превышает 12 месяцев, при этом цель не разбита на промежуточные этапы или контрольные точки";

MERGE (t:CheckTarget {name: "работы_без_наряда_допуска"})
SET t.description = "цель предполагает выполнение работ повышенной опасности (высота, электроустановки, огневые, газоопасные работы) без упоминания наряда-допуска";

// ---------- Пункты приказа ПР-2024-15 ----------
MATCH (o:Order {orderId: "PR-2024-15"})
MERGE (c:Clause {clauseId: "PR-2024-15/3.1"})
SET c.code = "п. 3.1",
    c.text = "Запрещается указывать в целях персональные данные сотрудников."
MERGE (o)-[:CONTAINS]->(c);

MATCH (o:Order {orderId: "PR-2024-15"})
MERGE (c:Clause {clauseId: "PR-2024-15/3.2"})
SET c.code = "п. 3.2",
    c.text = "Цель должна содержать измеримый показатель и срок исполнения."
MERGE (o)-[:CONTAINS]->(c);

MATCH (o:Order {orderId: "PR-2024-15"})
MERGE (c:Clause {clauseId: "PR-2024-15/4.1"})
SET c.code = "п. 4.1",
    c.text = "Запрещается ставить цели, срок которых превышает 12 месяцев без разбиения на этапы."
MERGE (o)-[:CONTAINS]->(c);

// ---------- Пункты приказа ПР-2024-22 ----------
MATCH (o:Order {orderId: "PR-2024-22"})
MERGE (c:Clause {clauseId: "PR-2024-22/2.5"})
SET c.code = "п. 2.5",
    c.text = "Не допускается формулировка целей, предполагающих работы без наряда-допуска."
MERGE (o)-[:CONTAINS]->(c);

// ---------- Правила ----------
MATCH (c:Clause {clauseId: "PR-2024-15/3.1"})
MERGE (r:Rule {ruleId: "R-001"})
SET r.type = "PROHIBITION",
    r.description = "Запрет на упоминание персональных данных (ФИО, телефон, паспорт) в тексте цели.",
    r.checkInstruction = "Переформулируйте цель обезличенно: укажите подразделение, роль или объект вместо конкретного сотрудника."
MERGE (c)-[:DEFINES]->(r);

MATCH (c:Clause {clauseId: "PR-2024-15/3.2"})
MERGE (r:Rule {ruleId: "R-002"})
SET r.type = "REQUIREMENT",
    r.description = "Цель обязана содержать измеримый показатель и срок исполнения.",
    r.checkInstruction = "Добавьте в формулировку числовой показатель результата и дату или период завершения."
MERGE (c)-[:DEFINES]->(r);

MATCH (c:Clause {clauseId: "PR-2024-15/4.1"})
MERGE (r:Rule {ruleId: "R-003"})
SET r.type = "PROHIBITION",
    r.description = "Запрет на цели длительностью более 12 месяцев без разбиения на этапы.",
    r.checkInstruction = "Разбейте цель на этапы продолжительностью не более 12 месяцев с отдельными контрольными точками."
MERGE (c)-[:DEFINES]->(r);

MATCH (c:Clause {clauseId: "PR-2024-22/2.5"})
MERGE (r:Rule {ruleId: "R-004"})
SET r.type = "PROHIBITION",
    r.description = "Запрет на постановку целей, предполагающих работы повышенной опасности без наряда-допуска.",
    r.checkInstruction = "Укажите в цели оформление наряда-допуска либо исключите из формулировки работы повышенной опасности."
MERGE (c)-[:DEFINES]->(r);

// ---------- Привязка правил к атрибутам ----------
MATCH (r:Rule {ruleId: "R-001"}), (t:CheckTarget {name: "персональные_данные"})
MERGE (r)-[:APPLIES_TO]->(t);

MATCH (r:Rule {ruleId: "R-002"}), (t:CheckTarget {name: "измеримость"})
MERGE (r)-[:APPLIES_TO]->(t);

MATCH (r:Rule {ruleId: "R-002"}), (t:CheckTarget {name: "срок_исполнения"})
MERGE (r)-[:APPLIES_TO]->(t);

MATCH (r:Rule {ruleId: "R-003"}), (t:CheckTarget {name: "срок_свыше_12_месяцев_без_этапов"})
MERGE (r)-[:APPLIES_TO]->(t);

MATCH (r:Rule {ruleId: "R-004"}), (t:CheckTarget {name: "работы_без_наряда_допуска"})
MERGE (r)-[:APPLIES_TO]->(t);

// ---------- Примеры ----------
// isViolation: true  — так формулировать НЕЛЬЗЯ (для PROHIBITION)
// isViolation: false — так формулировать НУЖНО (для REQUIREMENT)

MATCH (r:Rule {ruleId: "R-001"})
MERGE (e:ViolationExample {exampleId: "EX-001"})
SET e.isViolation = true,
    e.text = "Провести аудит рабочего места Иванова И.И., тел. +7-900-000-00-00."
MERGE (r)-[:HAS_EXAMPLE]->(e);

MATCH (r:Rule {ruleId: "R-001"})
MERGE (e:ViolationExample {exampleId: "EX-002"})
SET e.isViolation = false,
    e.text = "Провести аудит рабочих мест отдела логистики."
MERGE (r)-[:HAS_EXAMPLE]->(e);

MATCH (r:Rule {ruleId: "R-002"})
MERGE (e:ViolationExample {exampleId: "EX-003"})
SET e.isViolation = false,
    e.text = "Снизить долю просроченных заявок до 5 процентов к 31.12.2024."
MERGE (r)-[:HAS_EXAMPLE]->(e);

MATCH (r:Rule {ruleId: "R-002"})
MERGE (e:ViolationExample {exampleId: "EX-004"})
SET e.isViolation = true,
    e.text = "Улучшить работу с заявками."
MERGE (r)-[:HAS_EXAMPLE]->(e);

MATCH (r:Rule {ruleId: "R-003"})
MERGE (e:ViolationExample {exampleId: "EX-005"})
SET e.isViolation = true,
    e.text = "Модернизировать производственную линию в течение трёх лет."
MERGE (r)-[:HAS_EXAMPLE]->(e);

MATCH (r:Rule {ruleId: "R-003"})
MERGE (e:ViolationExample {exampleId: "EX-006"})
SET e.isViolation = false,
    e.text = "Этап 1: подготовить проект модернизации линии до 30.06.2025."
MERGE (r)-[:HAS_EXAMPLE]->(e);

MATCH (r:Rule {ruleId: "R-004"})
MERGE (e:ViolationExample {exampleId: "EX-007"})
SET e.isViolation = true,
    e.text = "Выполнить замену светильников на высоте 8 метров силами дежурной смены."
MERGE (r)-[:HAS_EXAMPLE]->(e);

MATCH (r:Rule {ruleId: "R-004"})
MERGE (e:ViolationExample {exampleId: "EX-008"})
SET e.isViolation = false,
    e.text = "Выполнить замену светильников на высоте по наряду-допуску до 01.09.2025."
MERGE (r)-[:HAS_EXAMPLE]->(e);

// ---------- Перекрёстные ссылки между пунктами ----------
MATCH (a:Clause {clauseId: "PR-2024-15/4.1"}), (b:Clause {clauseId: "PR-2024-15/3.2"})
MERGE (a)-[:REFERENCES]->(b);
