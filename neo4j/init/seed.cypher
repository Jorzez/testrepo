// ---------- Constraints (выполняется один раз) ----------
CREATE CONSTRAINT order_id  IF NOT EXISTS FOR (o:Order)  REQUIRE o.order_id  IS UNIQUE;
CREATE CONSTRAINT clause_id IF NOT EXISTS FOR (c:Clause) REQUIRE c.clause_id IS UNIQUE;
CREATE CONSTRAINT rule_id   IF NOT EXISTS FOR (r:Rule)   REQUIRE r.rule_id   IS UNIQUE;
CREATE CONSTRAINT attr_name IF NOT EXISTS FOR (a:GoalAttribute) REQUIRE a.name IS UNIQUE;

CREATE FULLTEXT INDEX rule_text_ft IF NOT EXISTS
FOR (r:Rule) ON EACH [r.text];

// ---------- Приказы ----------
CREATE (o1:Order {order_id: "PR-2024-15", title: "Об утверждении требований к формулировке целей",
                  date: date("2024-03-01"), status: "active"});
CREATE (o2:Order {order_id: "PR-2024-22", title: "О безопасности при постановке задач",
                  date: date("2024-06-10"), status: "active"});

// ---------- Пункты ----------
MATCH (o1:Order {order_id: "PR-2024-15"})
CREATE (o1)-[:CONTAINS]->(c1:Clause {clause_id: "PR-2024-15/п.3.1",
        number: "3.1", text: "Запрещается указывать в целях персональные данные сотрудников."}),
       (o1)-[:CONTAINS]->(c2:Clause {clause_id: "PR-2024-15/п.3.2",
        number: "3.2", text: "Цель должна содержать измеримый показатель и срок исполнения."}),
       (o1)-[:CONTAINS]->(c3:Clause {clause_id: "PR-2024-15/п.4.1",
        number: "4.1", text: "Запрещается ставить цели, срок которых превышает 12 месяцев без разбиения на этапы."});

MATCH (o2:Order {order_id: "PR-2024-22"})
CREATE (o2)-[:CONTAINS]->(c4:Clause {clause_id: "PR-2024-22/п.2.5",
        number: "2.5", text: "Не допускается формулировка целей, предполагающих работы без наряда-допуска."});

// ---------- Правила ----------
MATCH (c1:Clause {clause_id: "PR-2024-15/п.3.1"})
CREATE (c1)-[:DEFINES]->(r1:Rule {rule_id: "R-001", rule_type: "PROHIBITION",
        text: "Запрет на упоминание персональных данных (ФИО, телефон, паспорт) в тексте цели."});

MATCH (c2:Clause {clause_id: "PR-2024-15/п.3.2"})
CREATE (c2)-[:DEFINES]->(r2:Rule {rule_id: "R-002", rule_type: "OBLIGATION",
        text: "Цель обязана содержать измеримый KPI и дедлайн."});

MATCH (c3:Clause {clause_id: "PR-2024-15/п.4.1"})
CREATE (c3)-[:DEFINES]->(r3:Rule {rule_id: "R-003", rule_type: "PROHIBITION",
        text: "Запрет на цели длительностью более 12 месяцев без этапов."});

MATCH (c4:Clause {clause_id: "PR-2024-22/п.2.5"})
CREATE (c4)-[:DEFINES]->(r4:Rule {rule_id: "R-004", rule_type: "PROHIBITION",
        text: "Запрет на работы без наряда-допуска."});

// ---------- Требования ----------
MATCH (r2:Rule {rule_id: "R-002"})
CREATE (r2)-[:REQUIRES]->(:Requirement {req_id: "REQ-001", text: "Наличие числового KPI"}),
       (r2)-[:REQUIRES]->(:Requirement {req_id: "REQ-002", text: "Наличие даты дедлайна"});

MATCH (r3:Rule {rule_id: "R-003"})
CREATE (r3)-[:REQUIRES]->(:Requirement {req_id: "REQ-003",
        text: "Максимальный срок цели", max_value: 12, unit: "месяц"});

// ---------- Атрибуты цели (нормализованный словарь) ----------
MERGE (a1:GoalAttribute {name: "персональные_данные"});
MERGE (a2:GoalAttribute {name: "срок_исполнения"});
MERGE (a3:GoalAttribute {name: "измеримость"});
MERGE (a4:GoalAttribute {name: "охрана_труда"});

MATCH (r1:Rule {rule_id: "R-001"}), (a1:GoalAttribute {name: "персональные_данные"})
CREATE (r1)-[:APPLIES_TO]->(a1);
MATCH (r2:Rule {rule_id: "R-002"}), (a2:GoalAttribute {name: "срок_исполнения"})
CREATE (r2)-[:APPLIES_TO]->(a2);
MATCH (r2:Rule {rule_id: "R-002"}), (a3:GoalAttribute {name: "измеримость"})
CREATE (r2)-[:APPLIES_TO]->(a3);
MATCH (r3:Rule {rule_id: "R-003"}), (a2:GoalAttribute {name: "срок_исполнения"})
CREATE (r3)-[:APPLIES_TO]->(a2);
MATCH (r4:Rule {rule_id: "R-004"}), (a4:GoalAttribute {name: "охрана_труда"})
CREATE (r4)-[:APPLIES_TO]->(a4);

// ---------- Примеры ----------
MATCH (r1:Rule {rule_id: "R-001"})
CREATE (r1)-[:HAS_EXAMPLE]->(:Example {example_id: "EX-001", kind: "bad",
        text: "Провести аудит рабочего места Иванова И.И., тел. +7-900-..."}),
       (r1)-[:HAS_EXAMPLE]->(:Example {example_id: "EX-002", kind: "good",
        text: "Провести аудит рабочих мест отдела логистики."});

// ---------- Перекрёстные ссылки ----------
MATCH (c3:Clause {clause_id: "PR-2024-15/п.4.1"}),
      (c2:Clause {clause_id: "PR-2024-15/п.3.2"})
CREATE (c3)-[:REFERENCES]->(c2);