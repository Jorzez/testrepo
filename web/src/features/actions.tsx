import { api } from "../api/client";
import type { CheckTarget, Clause, Department, Example, Order, Rule, RuleType, Status } from "../api/types";
import { useCatalog } from "../state/catalog";
import { findOrderOf } from "../state/tree";
import { Chip } from "../ui/common";
import { useDialogs, type Option } from "../ui/Dialogs";
import type { MenuItem } from "../ui/Menu";
import { errorText, useToast } from "../ui/Toasts";
import { usePropertiesEditor } from "./PropertiesDialog";
import { useRuleScopeEditor } from "./RuleScopeDialog";

/* Все операции над узлами каталога. Каждая либо открывает форму, либо
   спрашивает подтверждение, а после изменения перечитывает данные. */

const RULE_TYPE_OPTIONS: Option[] = [
  { value: "REQUIREMENT", label: "Требование — нарушено, если атрибута НЕТ в цели" },
  { value: "PROHIBITION", label: "Запрет — нарушен, если атрибут ЕСТЬ в цели" },
];

const str = (v: unknown) => (v as string) ?? "";

export function useActions() {
  const catalog = useCatalog();
  const { orders, targets, clauses, mutate, expand } = catalog;
  const { openForm, confirm } = useDialogs();
  const toast = useToast();
  const editProperties = usePropertiesEditor();
  const editRuleScope = useRuleScopeEditor();

  /** Ошибки действий, не прошедших через форму, показываются уведомлением. */
  const run = (fn: () => Promise<unknown>) => () => { fn().catch((err) => toast(errorText(err), "err")); };

  const targetOptions = (): Option[] => targets.filter((t) => t.status !== "archived")
    .map((t) => ({ value: t.name, label: t.name, description: t.description }));
  const clauseOptions = (exclude?: string): Option[] => clauses.filter((c) => c.nodeId !== exclude)
    .map((c) => ({ value: c.nodeId, label: `${c.order_number} — ${c.code}` }));

  /** target передаётся для атрибута: архив используемого атрибута подтверждается отдельно. */
  const archive = (nodeId: string, target?: CheckTarget) => run(async () => {
    const usedBy = target?.rules ?? [];
    if (usedBy.length) {
      const ok = await confirm({
        title: "Атрибут используется",
        confirmLabel: "Всё равно в архив",
        message: <>
          <p>На атрибут <b>{target!.name}</b> ссылаются правила:{" "}
            {usedBy.map((r) => <Chip key={r}>{r}</Chip>)}.</p>
          <p className="muted">В архиве он перестанет участвовать в проверках, и эти правила
            по нему срабатывать не будут.</p>
        </>,
      });
      if (!ok) return;
    }
    await mutate(() => api.setStatus(nodeId, "archived"), "В архиве");
  });

  const restore = (nodeId: string) => run(() => mutate(() => api.setStatus(nodeId, "active"), "Восстановлено"));

  const remove = (nodeId: string) => run(async () => {
    const counts = await api.descendants(nodeId);
    const parts = [
      counts.clauses ? <><b>{counts.clauses}</b> пункт(ов)</> : null,
      counts.rules ? <><b>{counts.rules}</b> правил(а)</> : null,
      counts.examples ? <><b>{counts.examples}</b> пример(ов)</> : null,
    ].filter(Boolean);
    const ok = await confirm({
      title: "Удалить навсегда?", danger: true, confirmLabel: "Удалить",
      message: <>
        <p>Узел будет удалён из базы{parts.length ? <> вместе с {parts.map((p, i) =>
          <span key={i}>{i ? ", " : ""}{p}</span>)}</> : null}.</p>
        <p className="muted">Это необратимо и не требует предварительного архивирования.
          Если нужно просто отключить узел от проверок — используйте «В архив», это обратимо.</p>
      </>,
    });
    if (!ok) return;
    // Подтверждение уже спрошено явно, поэтому force: архивировать заранее не нужно.
    await mutate(() => api.remove(nodeId, true), "Удалено");
  });

  const statusItems = (node: { nodeId: string; status: Status }, target?: CheckTarget): MenuItem[] => [
    null,
    node.status === "archived"
      ? { label: "Вернуть", run: restore(node.nodeId) }
      : { label: "В архив", run: archive(node.nodeId, target) },
    { label: "Удалить", run: remove(node.nodeId), danger: true },
  ];

  const props = (nodeId: string) => () => editProperties(nodeId);

  // ------------------------------- приказы ---------------------------------

  const addOrder = () => openForm({
    title: "Новый приказ", submitLabel: "Создать",
    fields: [
      { name: "number", label: "Номер", required: true, placeholder: "ПР-01" },
      { name: "title", label: "Заголовок", type: "textarea", required: true, placeholder: "О порядке постановки целей" },
      { name: "date", label: "Дата", type: "date" },
      { name: "orderId", label: "Идентификатор", placeholder: "необязательно",
        hint: "Если не заполнить — будет построен из номера." },
    ],
    onSubmit: (v) => mutate(() => api.createOrder({
      number: str(v.number), title: str(v.title), date: str(v.date) || null, orderId: str(v.orderId) || null,
    }), "Приказ создан"),
  });

  const editOrder = (o: Order) => () => openForm({
    title: "Приказ " + (o.number ?? ""),
    fields: [
      { name: "number", label: "Номер", value: o.number, required: true },
      { name: "title", label: "Заголовок", type: "textarea", value: o.title, required: true },
      { name: "date", label: "Дата", type: "date", value: o.date ?? "" },
      { name: "orderId", label: "Идентификатор (orderId)", value: o.orderId ?? "", required: true,
        hint: "Ключ для выгрузки в seed.cypher. Должен быть уникален." },
    ],
    onSubmit: (v) => mutate(() => api.patch(o.nodeId, {
      number: v.number, title: v.title, date: str(v.date) || null, orderId: v.orderId,
    }), "Приказ обновлён"),
  });

  const orderMenu = (o: Order): MenuItem[] => [
    { label: "Изменить", run: editOrder(o) },
    { label: "Создать пункт", run: addClause(o.nodeId) },
    { label: "Свойства", run: props(o.nodeId) },
    ...statusItems(o),
  ];

  // -------------------------------- пункты ---------------------------------

  const addClause = (orderNodeId: string) => () => openForm({
    title: "Новый пункт", submitLabel: "Создать",
    fields: [
      { name: "code", label: "Номер пункта", required: true, placeholder: "3.1" },
      { name: "text", label: "Текст пункта", type: "textarea", required: true },
    ],
    onSubmit: (v) => mutate(async () => {
      await api.createClause({ orderNodeId, code: str(v.code), text: str(v.text) });
      expand([orderNodeId], []);
    }, "Пункт добавлен"),
  });

  const editClause = (c: Clause) => () => openForm({
    title: "Пункт " + (c.code ?? ""),
    fields: [
      { name: "code", label: "Номер пункта", value: c.code, required: true },
      { name: "text", label: "Текст пункта", type: "textarea", value: c.text, required: true },
      { name: "clauseId", label: "Идентификатор (clauseId)", value: c.clauseId ?? "", required: true },
    ],
    onSubmit: (v) => mutate(() => api.patch(c.nodeId, v), "Пункт обновлён"),
  });

  const clauseRefs = (c: Clause) => () => openForm({
    title: "Перекрёстные ссылки пункта " + (c.code ?? ""),
    fields: [{
      name: "references", label: "Ссылается на пункты", type: "multi",
      value: c.references.map((r) => r.nodeId), options: clauseOptions(c.nodeId),
      emptyText: "Других пунктов пока нет.",
      hint: "Связь (:Clause)-[:REFERENCES]->(:Clause). На проверку не влияет, нужна для навигации по нормативке.",
    }],
    onSubmit: (v) => mutate(() => api.setReferences(c.nodeId, v.references as string[]), "Ссылки обновлены"),
  });

  const moveClause = (c: Clause) => () => openForm({
    title: "Перенести пункт в другой приказ",
    fields: [{
      name: "parentNodeId", label: "Приказ", type: "select",
      value: findOrderOf(orders, c.nodeId)?.order.nodeId ?? orders[0]?.nodeId ?? "",
      options: orders.map((o) => ({ value: o.nodeId, label: o.number || o.orderId || o.nodeId })),
    }],
    onSubmit: (v) => mutate(() => api.moveClause(c.nodeId, str(v.parentNodeId)), "Пункт перенесён"),
  });

  const clauseMenu = (c: Clause): MenuItem[] => [
    { label: "Изменить", run: editClause(c) },
    { label: "Создать правило", run: addRule(c.nodeId) },
    { label: "Свойства", run: props(c.nodeId) },
    { label: "Ссылки", run: clauseRefs(c) },
    { label: "Перенести", run: moveClause(c) },
    ...statusItems(c),
  ];

  // ------------------------------- правила ---------------------------------

  const addRule = (clauseNodeId: string) => () => openForm({
    title: "Новое правило", submitLabel: "Создать",
    fields: [
      { name: "type", label: "Тип", type: "select", value: "REQUIREMENT", options: RULE_TYPE_OPTIONS },
      { name: "description", label: "Формулировка правила", type: "textarea", required: true,
        placeholder: "Цель обязана содержать конкретный срок исполнения" },
      { name: "checkInstruction", label: "Что подсказать автору цели", type: "textarea",
        placeholder: "Добавьте в формулировку дату или период завершения",
        hint: "Текст попадает в ответ проверки как check_instruction." },
      { name: "targets", label: "Атрибуты", type: "multi", value: [], options: targetOptions(),
        emptyText: "Атрибутов нет — заведите их на вкладке «Атрибуты».",
        hint: "Правило без атрибутов никогда не сработает." },
    ],
    onSubmit: (v) => mutate(async () => {
      await api.createRule({
        clauseNodeId, type: v.type as RuleType, description: str(v.description),
        checkInstruction: str(v.checkInstruction), targets: v.targets as string[],
      });
      expand([], [clauseNodeId]);
    }, "Правило создано"),
  });

  const editRule = (r: Rule) => () => openForm({
    title: "Правило " + (r.ruleId ?? ""),
    fields: [
      { name: "type", label: "Тип", type: "select", value: r.type ?? "REQUIREMENT", options: RULE_TYPE_OPTIONS },
      { name: "description", label: "Формулировка правила", type: "textarea", value: r.description, required: true },
      { name: "checkInstruction", label: "Что подсказать автору цели", type: "textarea", value: r.checkInstruction },
      { name: "ruleId", label: "Идентификатор (ruleId)", value: r.ruleId ?? "", required: true },
    ],
    onSubmit: (v) => mutate(() => api.patch(r.nodeId, v), "Правило обновлено"),
  });

  const ruleTargets = (r: Rule) => () => openForm({
    title: "Атрибуты правила " + (r.ruleId ?? ""),
    fields: [{
      name: "targets", label: "Применяется к атрибутам", type: "multi",
      value: r.targets, options: targetOptions(),
      emptyText: "Атрибутов нет — заведите их на вкладке «Атрибуты».",
      hint: r.type === "PROHIBITION"
        ? "Запрет сработает, если хотя бы один из атрибутов найден в цели."
        : "Требование сработает по каждому атрибуту, которого в цели нет.",
    }],
    onSubmit: (v) => mutate(() => api.setRuleTargets(r.nodeId, v.targets as string[]), "Привязка обновлена"),
  });

  const moveRule = (r: Rule) => () => {
    const options = clauseOptions();
    openForm({
      title: "Перенести правило в другой пункт",
      fields: [{ name: "parentNodeId", label: "Пункт", type: "select",
        value: findOrderOf(orders, r.nodeId)?.clause?.nodeId ?? options[0]?.value ?? "", options }],
      onSubmit: (v) => mutate(() => api.moveRule(r.nodeId, str(v.parentNodeId)), "Правило перенесено"),
    });
  };

  const ruleScope = (r: Rule) => () => editRuleScope(r);

  const ruleMenu = (r: Rule): MenuItem[] => [
    { label: "Изменить", run: editRule(r) },
    { label: "Атрибуты", run: ruleTargets(r) },
    { label: "Подразделения", run: ruleScope(r) },
    { label: "Создать пример", run: addExample(r) },
    { label: "Свойства", run: props(r.nodeId) },
    { label: "Перенести", run: moveRule(r) },
    ...statusItems(r),
  ];

  // ------------------------------- примеры ---------------------------------

  const addExample = (r: Rule) => () => openForm({
    title: "Пример к правилу " + (r.ruleId ?? ""),
    submitLabel: "Добавить",
    fields: [
      { name: "text", label: "Формулировка", type: "textarea", required: true },
      { name: "isViolation", label: "Это пример нарушения", type: "checkbox", value: r.type === "PROHIBITION",
        hint: r.type === "PROHIBITION"
          ? "Запрет показывает в ответе именно примеры нарушений — галочку обычно оставляют."
          : "Требование показывает в ответе образцы правильных формулировок — галочку обычно снимают." },
    ],
    onSubmit: (v) => mutate(() => api.createExample({
      ruleNodeId: r.nodeId, text: str(v.text), isViolation: !!v.isViolation,
    }), "Пример добавлен"),
  });

  const editExample = (e: Example) => () => openForm({
    title: "Пример " + (e.exampleId ?? ""),
    fields: [
      { name: "text", label: "Формулировка", type: "textarea", value: e.text, required: true },
      { name: "isViolation", label: "Это пример нарушения", type: "checkbox", value: !!e.isViolation },
      { name: "exampleId", label: "Идентификатор (exampleId)", value: e.exampleId ?? "", required: true },
    ],
    onSubmit: (v) => mutate(() => api.patch(e.nodeId, v), "Пример обновлён"),
  });

  const deleteExample = (e: Example) => run(async () => {
    const ok = await confirm({
      title: "Удалить пример?", danger: true, confirmLabel: "Удалить",
      message: <p>Пример будет удалён из базы. Примеры не архивируются — их легко создать заново.</p>,
    });
    if (ok) await mutate(() => api.remove(e.nodeId), "Пример удалён");
  });

  // ------------------------------- атрибуты --------------------------------

  const addTarget = () => openForm({
    title: "Новый атрибут", submitLabel: "Создать",
    fields: [
      { name: "name", label: "Имя", required: true, placeholder: "срок_исполнения",
        hint: "Написание с пробелом и с подчёркиванием считается одним атрибутом — двойник создать не получится." },
      { name: "description", label: "Описание для модели", type: "textarea", required: true,
        placeholder: "в цели указан проверяемый срок: конкретная дата, месяц, квартал или год",
        hint: "Это перечисление признаков, по которым модель решает, есть атрибут в цели или нет." },
    ],
    onSubmit: (v) => mutate(() => api.createTarget({ name: str(v.name), description: str(v.description) }),
      "Атрибут создан"),
  });

  const editTarget = (t: CheckTarget) => () => openForm({
    title: "Атрибут " + t.name,
    fields: [
      { name: "name", label: "Имя", value: t.name, required: true,
        hint: "Переименование не меняет привязку правил: связь идёт по узлу." },
      { name: "description", label: "Описание для модели", type: "textarea", value: t.description, required: true },
    ],
    onSubmit: (v) => mutate(() => api.patch(t.nodeId, v), "Атрибут обновлён"),
  });

  const targetMenu = (t: CheckTarget): MenuItem[] => [
    { label: "Изменить", run: editTarget(t) },
    { label: "Свойства", run: props(t.nodeId) },
    ...statusItems(t, t),
  ];

  // ----------------------------- подразделения ------------------------------

  const addDepartment = () => openForm({
    title: "Новое подразделение", submitLabel: "Создать",
    fields: [
      { name: "departmentId", label: "Идентификатор", required: true, placeholder: "UCT",
        hint: "Тот, что кадровая система передаёт в запросе проверки как department_id." },
      { name: "name", label: "Название", required: true, placeholder: "УЦТ" },
    ],
    onSubmit: (v) => mutate(() => api.createDepartment({
      departmentId: str(v.departmentId), name: str(v.name),
    }), "Подразделение создано"),
  });

  const editDepartment = (d: Department) => () => openForm({
    title: "Подразделение " + (d.name || d.departmentId || ""),
    fields: [
      { name: "departmentId", label: "Идентификатор", value: d.departmentId ?? "", required: true,
        hint: "Смена идентификатора не рвёт связи с правилами, но запросы проверки должны передавать новый." },
      { name: "name", label: "Название", value: d.name, required: true },
    ],
    onSubmit: (v) => mutate(() => api.patch(d.nodeId, v), "Подразделение обновлено"),
  });

  const departmentMenu = (d: Department): MenuItem[] => [
    { label: "Изменить", run: editDepartment(d) },
    { label: "Свойства", run: props(d.nodeId) },
    ...statusItems(d),
  ];

  return {
    addOrder, addTarget, addDepartment, orderMenu, clauseMenu, ruleMenu, targetMenu, departmentMenu,
    ruleTargets, ruleScope,
    editExample, deleteExample, props, archive, restore,
  };
}
