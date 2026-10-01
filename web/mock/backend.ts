/* Фейковый API в памяти: для `npm run dev:mock` и для e2e-тестов.

   Повторяет ровно то поведение настоящего API, на которое опирается
   интерфейс: форма ответов, 404/409, каскадное удаление, запрет удалять
   используемый атрибут, защита от двойников по написанию. Это не замена
   тестам API — те живут в api/tests и проверяют настоящий код. */

type Props = Record<string, unknown>;
type Label = "Order" | "Clause" | "Rule" | "ViolationExample" | "CheckTarget" | "Department";

/** (:Rule)-[:EXCEPT_IN {status, basis, note}]->(:Department) */
interface Exception {
  rule: string;
  department: string;
  status: string;
  basis: string | null;
  note: string | null;
}

interface Node {
  id: string;
  label: Label;
  props: Props;
  parent?: string;          // CONTAINS / DEFINES / HAS_EXAMPLE
}

export interface Reply {
  status: number;
  body: unknown;
}

const BUSINESS_KEYS: Partial<Record<Label, string>> = {
  Order: "orderId", Clause: "clauseId", Rule: "ruleId", ViolationExample: "exampleId", CheckTarget: "name",
  Department: "departmentId",
};

export const normalizeName = (name: string) =>
  String(name).replace(/ /g, " ").trim().toLowerCase().replace(/ё/g, "е")
    .replace(/[\s-]+/g, "_").replace(/_+/g, "_").replace(/^_|_$/g, "");

class HttpError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

/** Начальные данные. Приказ ПР-02 заведён без бизнес-ключей — на такой
    конфигурации карточка приказа когда-то не раскрывалась. */
function seed() {
  const nodes: Node[] = [];
  const add = (id: string, label: Label, props: Props, parent?: string) =>
    nodes.push({ id, label, props, parent });

  add("t:1", "CheckTarget", { name: "проект", status: "active",
    description: "в цели явно назван проект, программа или инициатива, в рамках которой ведётся работа" });
  add("t:2", "CheckTarget", { name: "срок_исполнения", status: "active",
    description: "в цели указан проверяемый срок: конкретная дата, месяц, квартал или год" });
  add("t:3", "CheckTarget", { name: "обучение", status: "active", description: "" });

  add("o:1", "Order", { orderId: "PR-01", number: "ПР-01", title: "О порядке постановки целей",
    date: "2024-01-15", status: "active" });
  add("c:1", "Clause", { clauseId: "PR-01/1.1", code: "1.1", status: "active",
    text: "В цели должно быть упоминание проекта, в рамках которого производится работа" }, "o:1");
  add("r:1", "Rule", { ruleId: "R-1.1", type: "REQUIREMENT", status: "active",
    description: "Цель обязана содержать упоминание проекта",
    checkInstruction: "Проверь, указан ли в тексте цели проект." }, "c:1");
  add("e:1", "ViolationExample", { exampleId: "R-1.1-EX1", isViolation: false, status: "active",
    text: "В рамках проекта «Альфа» разработать API для интеграции до 01.06.2025" }, "r:1");
  add("e:2", "ViolationExample", { exampleId: "R-1.1-EX2", isViolation: true, status: "active",
    text: "Реализовать требования по автоматизации процесса в системе 1С:KPI" }, "r:1");
  add("c:2", "Clause", { clauseId: "PR-01/2.4", code: "2.4", status: "active",
    text: "Цель должна иметь конкретные сроки исполнения" }, "o:1");
  add("r:2", "Rule", { ruleId: "R-2.4", type: "REQUIREMENT", status: "active",
    description: "Цель обязана содержать конкретный срок исполнения",
    checkInstruction: "Формулировки 'в ближайшее время', 'по возможности' — нарушение." }, "c:2");
  add("e:3", "ViolationExample", { exampleId: "R-2.4-EX1", isViolation: false, status: "active",
    text: "Внедрить систему мониторинга в проекте «Бета» до 15.09.2025" }, "r:2");

  add("o:2", "Order", { number: "ПР-02", title: "Об обучении персонала" });
  add("c:3", "Clause", { code: "3.1", text: "Цель не должна сводиться к прохождению обучения" }, "o:2");
  add("r:3", "Rule", { type: "PROHIBITION", description: "Обучение само по себе целью не является" }, "c:3");

  add("d:1", "Department", { departmentId: "UCT", name: "УЦТ", status: "active" });
  add("d:2", "Department", { departmentId: "AGD", name: "АГД", status: "active" });
  add("d:3", "Department", { departmentId: "FIN", name: "Финансовое управление", status: "active" });

  const appliesTo: [string, string][] = [["r:1", "t:1"], ["r:2", "t:2"], ["r:3", "t:3"]];
  const references: [string, string][] = [["c:2", "c:1"]];
  // Проект обязателен только в УЦТ и АГД; срок в АГД не требуется по пункту
  // приказа, а в финансовом управлении — пока лишь по внутренней договорённости.
  const onlyIn: [string, string][] = [["r:1", "d:1"], ["r:1", "d:2"]];
  const exceptions: Exception[] = [
    { rule: "r:2", department: "d:2", status: "active", basis: "ПР-01 п. 2.5", note: null },
    { rule: "r:2", department: "d:3", status: "candidate", basis: null, note: "договорённость внутри управления" },
  ];
  return { nodes, appliesTo, references, onlyIn, exceptions };
}

export function createBackend() {
  const data = seed();
  const nodes = new Map(data.nodes.map((n) => [n.id, n]));
  let appliesTo = data.appliesTo;
  let references = data.references;
  let onlyIn = data.onlyIn;
  let exceptions = data.exceptions;
  let counter = 100;

  const statusOf = (n: Node) => (n.props.status === "archived" ? "archived" : "active");
  const children = (id: string) => [...nodes.values()].filter((n) => n.parent === id);
  const keep = (n: Node, archived: boolean) => archived || statusOf(n) === "active";
  const get = (id: string) => {
    const n = nodes.get(id);
    if (!n) throw new HttpError(404, `Узел ${id} не найден`);
    return n;
  };
  const ofLabel = (id: string, label: Label) => {
    const n = get(id);
    if (n.label !== label) throw new HttpError(404, `Узел ${id} не найден`);
    return n;
  };
  const byCode = (a: Props, b: Props, key: string) => String(a[key] ?? "").localeCompare(String(b[key] ?? ""));
  const targetName = (id: string) => String(nodes.get(id)?.props.name ?? "");
  const ruleTargets = (ruleId: string) =>
    appliesTo.filter(([r]) => r === ruleId).map(([, t]) => targetName(t)).sort();
  const departmentRef = (id: string) => ({
    departmentId: String(nodes.get(id)?.props.departmentId ?? ""), name: nodes.get(id)?.props.name ?? null,
  });
  const departmentById = (departmentId: string) =>
    [...nodes.values()].find((n) => n.label === "Department" && n.props.departmentId === departmentId);
  const withId = (n: Node): Props & { nodeId: string; status: string } =>
    ({ ...n.props, nodeId: n.id, status: statusOf(n) });
  const create = (prefix: string, label: Label, props: Props, parent?: string) => {
    const node: Node = { id: `${prefix}:${++counter}`, label, props: { ...props, status: "active" }, parent };
    nodes.set(node.id, node);
    return { nodeId: node.id, ...node.props };
  };

  function tree(archived: boolean) {
    const orderKey = (n: Node) => String(n.props.number ?? n.props.orderId ?? "");
    const orders = [...nodes.values()].filter((n) => n.label === "Order" && keep(n, archived))
      .sort((a, b) => orderKey(a).localeCompare(orderKey(b)));
    return {
      orders: orders.map((o) => ({
        ...withId(o),
        clauses: children(o.id).filter((c) => keep(c, archived)).map((c) => ({
          ...withId(c),
          rules: children(c.id).filter((r) => keep(r, archived)).map((r) => ({
            ...withId(r),
            targets: ruleTargets(r.id),
            onlyIn: onlyIn.filter(([rule]) => rule === r.id).map(([, d]) => departmentRef(d)),
            exceptions: exceptions.filter((e) => e.rule === r.id).map((e) => ({
              ...departmentRef(e.department), status: e.status, basis: e.basis, note: e.note,
            })),
            examples: children(r.id).filter((e) => keep(e, archived)).map(withId),
          })).sort((a, b) => byCode(a, b, "ruleId")),
          references: references.filter(([from]) => from === c.id)
            .map(([, to]) => ({ nodeId: to, code: String(nodes.get(to)?.props.code ?? "?") })),
        })).sort((a, b) => byCode(a, b, "code")),
      })),
    };
  }

  function targets(archived: boolean) {
    return [...nodes.values()].filter((n) => n.label === "CheckTarget" && keep(n, archived))
      .sort((a, b) => String(a.props.name).localeCompare(String(b.props.name)))
      .map((t) => ({
        ...withId(t),
        description: String(t.props.description ?? ""),
        rules: appliesTo.filter(([, tid]) => tid === t.id)
          .map(([rid]) => String(nodes.get(rid)?.props.ruleId ?? "")).filter(Boolean).sort(),
      }));
  }

  function departments(archived: boolean) {
    const ruleId = (id: string) => String(nodes.get(id)?.props.ruleId ?? "(без ruleId)");
    return [...nodes.values()].filter((n) => n.label === "Department" && keep(n, archived))
      .sort((a, b) => String(a.props.departmentId).localeCompare(String(b.props.departmentId)))
      .map((d) => ({
        ...withId(d),
        name: String(d.props.name ?? ""),
        onlyRules: onlyIn.filter(([, dep]) => dep === d.id).map(([rule]) => ruleId(rule)),
        exceptRules: exceptions.filter((e) => e.department === d.id)
          .map((e) => ({ ruleId: ruleId(e.rule), status: e.status })),
      }));
  }

  function setRuleScope(id: string, body: any) {
    ofLabel(id, "Rule");
    const only: string[] = body.only ?? [];
    const items: any[] = body.exceptions ?? [];
    const resolve = (departmentId: string) => {
      const d = departmentById(departmentId);
      if (!d) throw new HttpError(404, `Нет таких подразделений: ${departmentId}`);
      return d.id;
    };
    const both = only.filter((d) => items.some((e) => e.departmentId === d));
    if (both.length)
      throw new HttpError(409, "Подразделение не может быть одновременно в «действует только в» "
        + `и в исключениях: ${both.join(", ")}`);
    const next = items.map((e): Exception => {
      const basis = String(e.basis ?? "").trim() || null;
      const status = e.status ?? "candidate";
      if (status === "active" && !basis)
        throw new HttpError(409, `Исключению для ${e.departmentId} нужно основание — код пункта приказа, `
          + "который его вводит. Без основания оно может быть только кандидатом.");
      return { rule: id, department: resolve(e.departmentId), status, basis,
        note: String(e.note ?? "").trim() || null };
    });
    const nextOnly = only.map((d): [string, string] => [id, resolve(d)]);
    onlyIn = [...onlyIn.filter(([rule]) => rule !== id), ...nextOnly];
    exceptions = [...exceptions.filter((e) => e.rule !== id), ...next];
    return { only, exceptions: items };
  }

  function descendants(id: string) {
    const all: Node[] = [];
    const walk = (pid: string) => children(pid).forEach((c) => { all.push(c); walk(c.id); });
    walk(id);
    return all;
  }

  function counts(id: string) {
    const d = descendants(id);
    return {
      clauses: d.filter((n) => n.label === "Clause").length,
      rules: d.filter((n) => n.label === "Rule").length,
      examples: d.filter((n) => n.label === "ViolationExample").length,
    };
  }

  function drop(id: string) {
    nodes.delete(id);
    appliesTo = appliesTo.filter(([r, t]) => r !== id && t !== id);
    references = references.filter(([a, b]) => a !== id && b !== id);
    onlyIn = onlyIn.filter(([rule, d]) => rule !== id && d !== id);
    exceptions = exceptions.filter((e) => e.rule !== id && e.department !== id);
  }

  function remove(id: string, force: boolean) {
    const n = get(id);
    if (n.label === "ViolationExample") { drop(id); return { deleted: id, examples: 1 }; }
    if (!force && statusOf(n) !== "archived")
      throw new HttpError(409, "Удалять можно только архивированный узел. Сначала отправьте его в архив.");
    if (n.label === "CheckTarget") {
      const used = appliesTo.filter(([, t]) => t === id).map(([r]) => String(nodes.get(r)?.props.ruleId ?? r));
      if (used.length)
        throw new HttpError(409, `Атрибут используется правилами: ${used.join(", ")}. Сначала отвяжите его.`);
      drop(id);
      return { deleted: id };
    }
    if (n.label === "Department") {
      const used = [...onlyIn.filter(([, d]) => d === id).map(([rule]) => rule),
        ...exceptions.filter((e) => e.department === id).map((e) => e.rule)]
        .map((rule) => String(nodes.get(rule)?.props.ruleId ?? rule));
      if (used.length)
        throw new HttpError(409, `Подразделение задаёт область действия правил: ${[...new Set(used)].join(", ")}. `
          + "Сначала уберите его из этих правил.");
      drop(id);
      return { deleted: id };
    }
    const stats = counts(id);
    descendants(id).forEach((d) => drop(d.id));
    drop(id);
    return { deleted: id, ...stats };
  }

  function patch(id: string, properties: Props) {
    const n = get(id);
    const key = BUSINESS_KEYS[n.label];
    if ("status" in properties) throw new HttpError(409, "Свойство 'status' меняется отдельной операцией");
    if (key && key in properties) {
      const value = properties[key];
      if (value === null || value === "") throw new HttpError(409, `${key} — ключ узла, его нельзя очистить`);
      const clash = [...nodes.values()].find((o) => o.label === n.label && o.id !== id && o.props[key] === value);
      if (clash) throw new HttpError(409, `${key} '${value}' уже занят другим узлом :${n.label}`);
    }
    for (const [k, v] of Object.entries(properties)) {
      if (v === null || (k === "date" && v === "")) delete n.props[k];
      else n.props[k] = v;
    }
    return { nodeId: n.id, labels: [n.label], ...n.props };
  }

  function createTarget(name: string, description: string) {
    const clash = [...nodes.values()].find((n) => n.label === "CheckTarget"
      && normalizeName(String(n.props.name)) === normalizeName(name));
    if (clash)
      throw new HttpError(409, `Атрибут с таким написанием уже есть: "${clash.props.name}". `
        + "Двойники ломают проверку — используйте существующий.");
    return create("t", "CheckTarget", { name, description });
  }

  function setRuleTargets(id: string, names: string[]) {
    ofLabel(id, "Rule");
    const ids = names.map((name) => {
      const t = [...nodes.values()].find((n) => n.label === "CheckTarget" && n.props.name === name);
      if (!t) throw new HttpError(404, `Атрибут "${name}" не найден`);
      return t.id;
    });
    appliesTo = [...appliesTo.filter(([r]) => r !== id), ...ids.map((t): [string, string] => [id, t])];
    return { targets: ruleTargets(id) };
  }

  function diagnostics() {
    const all = [...nodes.values()];
    const active = (label: Label) => all.filter((n) => n.label === label && statusOf(n) === "active");
    const issues: unknown[] = [];
    const issue = (code: string, severity: string, title: string, detail: string,
      items: unknown[] = [], fix: unknown = null) => issues.push({ code, severity, title, detail, items, fix });
    const kindOf = (n: Node) => ({ label: `${n.label} ${n.props.number ?? n.props.code ?? n.props.ruleId ?? n.id}`,
      nodeId: n.id, kind: n.label });

    const noDescription = active("CheckTarget").filter((t) => !String(t.props.description ?? "").trim());
    if (noDescription.length)
      issue("check_targets_without_description", "error", "Атрибуты без описания",
        "Модель получает в промпте только имя и системно не распознаёт атрибут.",
        noDescription.map((t) => ({ label: String(t.props.name), nodeId: t.id, kind: "CheckTarget" })));

    const noTargets = active("Rule").filter((r) => !appliesTo.some(([rid]) => rid === r.id));
    if (noTargets.length)
      issue("rules_without_target", "error", "Правила без привязки к атрибуту",
        "Правило не участвует ни в одном запросе проверки.", noTargets.map(kindOf));

    const noKey = all.filter((n) => n.label !== "CheckTarget" && n.label !== "Department"
      && !n.props[BUSINESS_KEYS[n.label]!]);
    if (noKey.length)
      issue("missing_identifiers", "error", "Узлы без идентификатора",
        "Без бизнес-ключа узел не попадёт в выгрузку seed.cypher.", noKey.map(kindOf),
        { action: "repair_identifiers", label: "Проставить идентификаторы" });

    const orphans = active("CheckTarget").filter((t) => !appliesTo.some(([, tid]) => tid === t.id));
    if (orphans.length)
      issue("orphan_check_targets", "warning", "Атрибуты без правил",
        "Тратят контекст модели, ни на что не влияя.",
        orphans.map((t) => ({ label: String(t.props.name), nodeId: t.id, kind: "CheckTarget" })));

    const candidates = exceptions.filter((e) => e.status === "candidate");
    if (candidates.length)
      issue("exception_candidates", "info", "Исключения-кандидаты ждут утверждения",
        "Пока владелец приказа их не утвердил, в вердикте они не участвуют.",
        candidates.map((e) => ({
          label: `${nodes.get(e.rule)?.props.ruleId ?? e.rule} — ${nodes.get(e.department)?.props.name}`,
          nodeId: e.rule, kind: "Rule",
        })));

    const archived = all.filter((n) => statusOf(n) === "archived");
    if (archived.length)
      issue("archived_nodes", "info", "В архиве", "Архивные узлы не участвуют в проверках.",
        [{ label: `Узлов: ${archived.length}` }]);

    const count = (s: string) => issues.filter((i) => (i as { severity: string }).severity === s).length;
    return {
      issues,
      counts: { error: count("error"), warning: count("warning"), info: count("info") },
      check_targets: active("CheckTarget").length,
      ready: count("error") === 0,
      problems: [],
    };
  }

  function repair() {
    const report = { orders: 0, clauses: 0, rules: 0, examples: 0, statuses: 0 };
    for (const n of nodes.values()) {
      const key = BUSINESS_KEYS[n.label]!;
      if (n.label !== "CheckTarget" && n.label !== "Department" && !n.props[key]) {
        n.props[key] = `${n.label.slice(0, 3).toUpperCase()}-${n.id}`;
        const field = { Order: "orders", Clause: "clauses", Rule: "rules", ViolationExample: "examples" }[
          n.label as "Order"] as keyof typeof report;
        report[field]++;
      }
      if (!n.props.status) { n.props.status = "active"; report.statuses++; }
    }
    return report;
  }

  /** Упрощённая проверка цели: атрибуты «находятся» по ключевым словам. */
  function checkGoal(goal: string, departmentId: string | null) {
    const notes = ["Ответ фейкового API: атрибуты определены по ключевым словам, без модели."];
    const allRules = "применены все правила, включая действующие только в отдельных "
      + "подразделениях; исключения не учитывались.";
    const found = departmentId ? departmentById(departmentId.trim()) : undefined;
    let department: Node | undefined;
    if (!departmentId?.trim()) notes.push("Подразделение не передано: " + allRules);
    else if (!found) notes.push(`Подразделения "${departmentId}" нет в графе (:Department): ${allRules}`);
    else if (statusOf(found) !== "active") notes.push(`Подразделение "${departmentId}" находится в архиве: ${allRules}`);
    else department = found;

    const text = goal.toLowerCase();
    const detected = [
      /проект/.test(text) ? "проект" : null,
      /\d{2}\.\d{2}\.\d{4}|квартал|\b20\d{2}\b/.test(text) ? "срок_исполнения" : null,
      /обучени|курс/.test(text) ? "обучение" : null,
    ].filter((a): a is string => !!a);

    const violations = [];
    const exemptions = [];
    for (const r of [...nodes.values()].filter((n) => n.label === "Rule" && statusOf(n) === "active")) {
      const clause = nodes.get(r.parent!)!;
      const order = nodes.get(clause.parent!)!;
      if (statusOf(clause) !== "active" || statusOf(order) !== "active") continue;
      const restricted = onlyIn.filter(([rule]) => rule === r.id).map(([, d]) => d);
      if (department && restricted.length && !restricted.includes(department.id)) continue;
      const exception = department
        ? exceptions.find((e) => e.rule === r.id && e.department === department.id) : undefined;
      for (const name of ruleTargets(r.id)) {
        const present = detected.includes(name);
        const prohibition = r.props.type === "PROHIBITION";
        if (prohibition ? !present : present) continue;
        const row = {
          order_number: order.props.number ?? null, order_title: order.props.title ?? null,
          clause_code: clause.props.code ?? null, clause_text: clause.props.text ?? null,
          rule_id: r.props.ruleId ?? null, rule_text: r.props.description ?? null,
          check_instruction: r.props.checkInstruction ?? null,
          violation_type: prohibition ? "PROHIBITION" : "MISSING_REQUIREMENT",
          attribute: name,
          example_kind: prohibition ? "violation" : "correct",
          examples: children(r.id).filter((e) => statusOf(e) === "active"
            && !!e.props.isViolation === prohibition).map((e) => e.props.text),
        };
        if (exception?.status === "active") exemptions.push({ ...row, basis: exception.basis, note: exception.note });
        else violations.push({ ...row, candidate_exception: exception?.status === "candidate"
          ? { basis: exception.basis, note: exception.note } : null });
      }
    }
    return {
      goal, status: violations.length ? "VIOLATIONS_FOUND" : "ALLOWED", allowed: !violations.length,
      department: department
        ? { id: String(department.props.departmentId), name: String(department.props.name ?? "") } : null,
      detected_attributes: detected, violations, exemptions, notes,
    };
  }

  function route(method: string, path: string, query: URLSearchParams, body: any): unknown {
    const archived = query.get("include_archived") === "true";
    const m = (re: RegExp) => path.match(re);
    let p: RegExpMatchArray | null;

    if (method === "GET" && path === "/health") return { status: "ok" };
    if (method === "GET" && path === "/catalog/tree") return tree(archived);
    if (method === "GET" && path === "/catalog/check-targets") return { targets: targets(archived) };
    if (method === "GET" && path === "/catalog/clauses")
      return {
        clauses: [...nodes.values()].filter((n) => n.label === "Clause").map((c) => ({
          nodeId: c.id, code: String(c.props.code ?? "?"), status: statusOf(c),
          order_number: String(nodes.get(c.parent!)?.props.number ?? nodes.get(c.parent!)?.props.orderId ?? "?"),
        })).sort((a, b) => (a.order_number + a.code).localeCompare(b.order_number + b.code)),
      };
    if (method === "GET" && path === "/catalog/departments") return { departments: departments(archived) };
    if (method === "GET" && path === "/catalog/diagnostics") return diagnostics();
    if (method === "POST" && path === "/catalog/repair-identifiers") return repair();
    if (method === "POST" && path === "/check-goal")
      return checkGoal(String(body?.goal ?? ""), body?.department_id ?? null);

    if ((p = m(/^\/catalog\/nodes\/([^/]+)$/))) {
      const id = decodeURIComponent(p[1]);
      if (method === "GET") { const n = get(id); return { nodeId: n.id, labels: [n.label], ...n.props }; }
      if (method === "DELETE") return remove(id, query.get("force") === "true");
    }
    if ((p = m(/^\/catalog\/nodes\/([^/]+)\/(properties|status|descendants)$/))) {
      const id = decodeURIComponent(p[1]);
      if (p[2] === "properties" && method === "PATCH") return patch(id, body?.properties ?? {});
      if (p[2] === "status" && method === "POST") { get(id).props.status = body.status; return { nodeId: id, status: body.status }; }
      if (p[2] === "descendants" && method === "GET") { get(id); return counts(id); }
    }

    if (method === "POST" && path === "/catalog/orders") {
      const orderId = body.orderId || String(body.number).toUpperCase().replace(/[^\p{L}\p{N}]+/gu, "-");
      if ([...nodes.values()].some((n) => n.label === "Order" && n.props.orderId === orderId))
        throw new HttpError(409, `orderId '${orderId}' уже занят`);
      return create("o", "Order", { number: body.number, title: body.title, orderId,
        ...(body.date ? { date: body.date } : {}) });
    }
    if (method === "POST" && path === "/catalog/clauses") {
      const order = ofLabel(body.orderNodeId, "Order");
      return create("c", "Clause", { code: body.code, text: body.text,
        clauseId: `${order.props.orderId ?? "ORD"}/${body.code}` }, order.id);
    }
    if (method === "POST" && path === "/catalog/rules") {
      ofLabel(body.clauseNodeId, "Clause");
      const rule = create("r", "Rule", { type: body.type, description: body.description,
        checkInstruction: body.checkInstruction, ruleId: `R-${counter + 1}` }, body.clauseNodeId);
      setRuleTargets(rule.nodeId, body.targets ?? []);
      return rule;
    }
    if (method === "POST" && path === "/catalog/examples") {
      ofLabel(body.ruleNodeId, "Rule");
      return create("e", "ViolationExample", { text: body.text, isViolation: !!body.isViolation,
        exampleId: `EX-${counter + 1}` }, body.ruleNodeId);
    }
    if (method === "POST" && path === "/catalog/check-targets")
      return createTarget(String(body.name), String(body.description ?? ""));

    if (method === "POST" && path === "/catalog/departments") {
      const departmentId = String(body.departmentId).trim();
      if (departmentById(departmentId))
        throw new HttpError(409, `Подразделение с идентификатором '${departmentId}' уже существует`);
      return create("d", "Department", { departmentId, name: String(body.name).trim() });
    }

    if (method === "PUT" && (p = m(/^\/catalog\/rules\/([^/]+)\/departments$/)))
      return setRuleScope(decodeURIComponent(p[1]), body ?? {});
    if (method === "PUT" && (p = m(/^\/catalog\/rules\/([^/]+)\/targets$/)))
      return setRuleTargets(decodeURIComponent(p[1]), body.targets ?? []);
    if (method === "PUT" && (p = m(/^\/catalog\/clauses\/([^/]+)\/references$/))) {
      const id = decodeURIComponent(p[1]);
      ofLabel(id, "Clause");
      references = [...references.filter(([a]) => a !== id),
        ...(body.references as string[]).map((to): [string, string] => [id, to])];
      return { references: body.references };
    }
    if (method === "POST" && (p = m(/^\/catalog\/(clauses|rules)\/([^/]+)\/move$/))) {
      const [label, parentLabel]: [Label, Label] = p[1] === "clauses" ? ["Clause", "Order"] : ["Rule", "Clause"];
      const n = ofLabel(decodeURIComponent(p[2]), label);
      n.parent = ofLabel(body.parentNodeId, parentLabel).id;
      return { nodeId: n.id, parentNodeId: n.parent };
    }
    throw new HttpError(404, `Not Found: ${method} ${path}`);
  }

  return {
    handle(method: string, url: string, body?: unknown): Reply {
      const parsed = new URL(url, "http://mock");
      try {
        const result = route(method.toUpperCase(), parsed.pathname, parsed.searchParams, body);
        return { status: method.toUpperCase() === "POST" && /^\/catalog\/(orders|clauses|rules|examples|check-targets|departments)$/
          .test(parsed.pathname) ? 201 : 200, body: result };
      } catch (err) {
        if (err instanceof HttpError) return { status: err.status, body: { detail: err.message } };
        return { status: 500, body: { detail: String(err) } };
      }
    },
  };
}
