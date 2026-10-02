// ============================================================
//  Схема графа нормативных требований к формулировке целей
//
//  Модель данных (совпадает с запросами в api/graph.py):
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
//  Разграничение по подразделениям:
//    (:Department {departmentId, name, status})
//    (:Rule)-[:ONLY_IN]->(:Department)      правило действует только в перечисленных
//    (:Rule)-[:EXCEPT_IN {status, basis, note}]->(:Department)
//                                           правило в подразделении не применяется;
//                                           status: active | candidate,
//                                           basis — пункт приказа, вводящий исключение
//    Правило без ONLY_IN действует для всех.
//
//  ------------------------------------------------------------
//  ДАННЫЕ ЗДЕСЬ НЕ ХРАНЯТСЯ ВРУЧНУЮ.
//
//  Источник истины — сама база. Чтобы зафиксировать её текущее
//  состояние в этом файле:
//
//      docker compose exec api python export_graph.py --output /init/seed.cypher
//
//  Скрипт выгружает приказы, пункты, правила, атрибуты, примеры и подразделения
//  в идемпотентный MERGE-скрипт, который дописывается ниже этого
//  комментария. После этого `docker compose up` воспроизводит граф
//  один в один, а diff в git показывает, что именно изменилось
//  в нормативке.
//
//  Демонстрационные приказы ПР-2024-15 и ПР-2024-22 удалены отсюда
//  намеренно: рабочий набор — ПР-01. Убрать их из уже поднятой базы:
//
//      docker compose run --rm \
//        -e SEED_FILE=/init/migrations/001_cleanup_demo_data.cypher seeder
//  ------------------------------------------------------------
//
//  Скрипт идемпотентен: схема создаётся через IF NOT EXISTS,
//  данные — через MERGE.
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

CREATE CONSTRAINT department_id IF NOT EXISTS
FOR (d:Department) REQUIRE d.departmentId IS UNIQUE;

// Реестр пользователей интерфейса (api/users.py). В выгрузку не попадает.
CREATE CONSTRAINT user_login IF NOT EXISTS
FOR (u:User) REQUIRE u.login IS UNIQUE;

CREATE FULLTEXT INDEX rule_description_ft IF NOT EXISTS
FOR (r:Rule) ON EACH [r.description];

// ---------- Данные ----------
// Ниже дописывается вывод export_graph.py.
