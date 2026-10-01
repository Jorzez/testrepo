import { useState } from "react";

import type { Clause, Example, Order, Rule } from "../../api/types";
import { useCatalog } from "../../state/catalog";
import { allClauses, clauseMatches, normalizeQuery, orderMatches } from "../../state/tree";
import { archivedClass, ArchivedBadge, Chip, IdBadge } from "../../ui/common";
import { MenuButton } from "../../ui/Menu";
import { useActions } from "../actions";

/* Дерево приказ → пункт → правило → атрибуты и примеры. Приказы и пункты
   сворачиваются независимо и по умолчанию свёрнуты; при поиске совпавшие
   узлы раскрываются сами. */

export function CatalogTab({ hidden }: { hidden: boolean }) {
  const { orders, showArchived, reload, expand, collapseAll } = useCatalog();
  const actions = useActions();
  const [search, setSearch] = useState("");
  const query = normalizeQuery(search);
  const visible = orders.filter((o) => orderMatches(o, query));

  return (
    <section id="tab-catalog" className={hidden ? "hidden" : ""}>
      <div className="toolbar">
        <input type="text" id="search" className="grow" value={search}
          placeholder="Поиск по номеру, заголовку, тексту пункта, правила или примера…"
          onChange={(e) => setSearch(e.target.value)} />
        <button className="btn sm" onClick={() =>
          expand(orders.map((o) => o.nodeId), allClauses(orders).map((c) => c.nodeId))}>Раскрыть все</button>
        <button className="btn sm" onClick={collapseAll}>Свернуть</button>
        <label className="check">
          <input type="checkbox" checked={showArchived}
            onChange={(e) => void reload({ showArchived: e.target.checked })} /> Архив
        </label>
        <button className="btn primary" onClick={actions.addOrder}>Создать</button>
      </div>
      <div id="tree">
        {visible.length
          ? visible.map((o) => <OrderCard key={o.nodeId} order={o} query={query} />)
          : <div className="empty">{search ? "Ничего не найдено." : "Приказов пока нет. Начните с кнопки «Создать»."}</div>}
      </div>
    </section>
  );
}

function OrderCard({ order, query }: { order: Order; query: string }) {
  const { openOrders, toggleOrder } = useCatalog();
  const actions = useActions();
  const open = openOrders.has(order.nodeId) || (!!query && orderMatches(order, query));
  const rules = order.clauses.reduce((n, c) => n + c.rules.length, 0);

  return (
    <div className={`card ${archivedClass(order.status)}`} data-node={order.nodeId}>
      <div className="order-head" onClick={() => toggleOrder(order.nodeId)}>
        <span className={`caret ${open ? "open" : ""}`}>▶</span>
        <div className="order-title">
          <b>{order.number || "(без номера)"}</b>{" "}
          <IdBadge value={order.orderId} name="orderId" /><ArchivedBadge status={order.status} />
          <div className="sub">{order.title}</div>
          <div className="dim">{order.clauses.length} п. · {rules} прав.{order.date ? " · " + order.date : ""}</div>
        </div>
        <div className="actions"><MenuButton items={() => actions.orderMenu(order)} /></div>
      </div>
      {open && (
        <div className="body">
          {order.clauses.length
            ? order.clauses.map((c) => <ClauseItem key={c.nodeId} clause={c} query={query} />)
            : <div className="dim" style={{ padding: "10px 0" }}>Пунктов нет.</div>}
        </div>
      )}
    </div>
  );
}

function ClauseItem({ clause, query }: { clause: Clause; query: string }) {
  const { openClauses, toggleClause } = useCatalog();
  const actions = useActions();
  const open = openClauses.has(clause.nodeId) || clauseMatches(clause, query);

  return (
    <div className={`clause ${archivedClass(clause.status)}`} data-node={clause.nodeId}>
      <div className="row">
        <div className="grow clause-head" onClick={() => toggleClause(clause.nodeId)}>
          <span className={`caret ${open ? "open" : ""}`}>▶</span>
          <div className="grow">
            <div className="row" style={{ alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <b>{clause.code || "(без номера)"}</b>
              <IdBadge value={clause.clauseId} name="clauseId" /><ArchivedBadge status={clause.status} />
              <span className="dim">{clause.rules.length} прав.</span>
            </div>
            <div style={{ marginTop: 3 }}>{clause.text}</div>
          </div>
        </div>
        <div className="actions"><MenuButton items={() => actions.clauseMenu(clause)} /></div>
      </div>
      {open && (
        <div style={{ paddingLeft: 28 }}>
          {clause.references.length > 0 && (
            <div className="targets">
              <span className="dim">ссылается на:</span>
              {clause.references.map((r) => <Chip key={r.nodeId}>→ {r.code}</Chip>)}
            </div>
          )}
          {clause.rules.map((r) => <RuleItem key={r.nodeId} rule={r} />)}
          {!clause.rules.length && <div className="dim" style={{ marginTop: 8 }}>Правил нет — пункт ничего не проверяет.</div>}
        </div>
      )}
    </div>
  );
}

function RuleItem({ rule }: { rule: Rule }) {
  const actions = useActions();
  return (
    <div className={`rule ${archivedClass(rule.status)}`} data-node={rule.nodeId}>
      <div className="row">
        <div className="grow">
          <div className="rule-meta">
            {rule.type === "PROHIBITION"
              ? <span className="badge prohibition">Запрет</span>
              : <span className="badge requirement">Требование</span>}
            <span className="mono">{rule.ruleId}</span>
            <IdBadge value={rule.ruleId} name="ruleId" /><ArchivedBadge status={rule.status} />
            {!rule.targets.length && <span className="badge warn">нет атрибутов — правило не сработает</span>}
          </div>
          <div>{rule.description}</div>
          {rule.checkInstruction && <div className="dim" style={{ marginTop: 5 }}>{rule.checkInstruction}</div>}
          <div className="targets">
            {rule.targets.map((t) => <Chip key={t}>{t}</Chip>)}
            <button className="btn sm ghost" onClick={actions.ruleTargets(rule)}>атрибуты…</button>
          </div>
          <div className="targets">
            {rule.onlyIn.length > 0 && <>
              <span className="dim">только в:</span>
              {rule.onlyIn.map((d) => <Chip key={d.departmentId}>{d.name || d.departmentId}</Chip>)}
            </>}
            {rule.exceptions.length > 0 && <>
              <span className="dim">не применяется в:</span>
              {rule.exceptions.map((e) => (
                <Chip key={e.departmentId}>
                  {e.name || e.departmentId}
                  {e.status === "active" ? (e.basis ? ` · ${e.basis}` : "") : " · кандидат"}
                </Chip>
              ))}
            </>}
            {!rule.onlyIn.length && !rule.exceptions.length && <span className="dim">для всех подразделений</span>}
            <button className="btn sm ghost" onClick={actions.ruleScope(rule)}>подразделения…</button>
          </div>
          {rule.examples.length
            ? <div className="examples">{rule.examples.map((e) => <ExampleRow key={e.nodeId} example={e} />)}</div>
            : <div className="dim" style={{ marginTop: 8 }}>Примеров нет — в ответе проверки поле examples будет пустым.</div>}
        </div>
        <div className="actions"><MenuButton items={() => actions.ruleMenu(rule)} /></div>
      </div>
    </div>
  );
}

/* У примеров кнопки остаются на виду: их всего три и они самые частые. */
function ExampleRow({ example: ex }: { example: Example }) {
  const actions = useActions();
  return (
    <div className={`example ${ex.isViolation ? "bad" : "good"} ${archivedClass(ex.status)}`} data-node={ex.nodeId}>
      <span className="mark">{ex.isViolation ? "✗" : "✓"}</span>
      <span className="grow">{ex.text} <ArchivedBadge status={ex.status} /></span>
      <span className="actions">
        <button className="btn sm ghost" onClick={actions.editExample(ex)}>изменить</button>
        <button className="btn sm ghost" onClick={actions.props(ex.nodeId)}>свойства</button>
        {ex.status === "archived"
          ? <button className="btn sm ghost" onClick={actions.restore(ex.nodeId)}>вернуть</button>
          : <button className="btn sm ghost" onClick={actions.archive(ex.nodeId)}>в архив</button>}
        <button className="btn sm ghost" onClick={actions.deleteExample(ex)}>удалить</button>
      </span>
    </div>
  );
}
