import { useState } from "react";

import { api } from "../../api/client";
import type { CheckResult, Exemption, Violation } from "../../api/types";
import { useCatalog } from "../../state/catalog";
import { cellState } from "../../state/scope";
import { activeRuleRefs, allRuleRefs } from "../../state/tree";
import { Chip, Spinner } from "../../ui/common";
import { Select } from "../../ui/Select";
import { errorText, useToast } from "../../ui/Toasts";

/* Главный экран: проверка формулировки цели. Ответ — человеческим языком:
   что не так, какой пункт приказа и как исправить. Справа — что именно
   проверяется для выбранного подразделения и что ждёт решения владельца. */

const place = (v: Violation | Exemption) =>
  `Приказ ${v.order_number ?? "?"}, пункт ${v.clause_code ?? "?"}${v.clause_text ? " — " + v.clause_text : ""}`;

export function CheckView() {
  const toast = useToast();
  const { orders, departments, health, setSection, setTrace, checkForm, setCheckForm } = useCatalog();
  const { goal, departmentId, result } = checkForm;
  const setGoal = (next: string) => setCheckForm({ goal: next });
  const setDepartmentId = (next: string) => setCheckForm({ departmentId: next });
  const setResult = (next: CheckResult | null) => setCheckForm({ result: next });
  const [busy, setBusy] = useState(false);
  const options = departments.filter((d) => d.departmentId && d.status === "active");
  const department = options.find((d) => d.departmentId === departmentId);

  // Что реально проверяется для подразделения — та же логика, что в графе.
  const active = activeRuleRefs(orders);
  const applicable = active.filter(({ rule }) => !departmentId || cellState(rule, departmentId).kind !== "off");
  const skipped = active.length - applicable.length;
  const candidates = allRuleRefs(orders).reduce(
    (n, { rule }) => n + rule.exceptions.filter((e) => e.status !== "active").length, 0);
  const problems = (health?.error ?? 0) + (health?.warning ?? 0);
  const failed = new Set(result?.violations.map((v) => v.rule_id));

  async function run() {
    const text = goal.trim();
    if (!text) { toast("Введите формулировку цели", "err"); return; }
    setBusy(true);
    setResult(null);
    try {
      setResult(await api.checkGoal(text, departmentId || null));
    } catch (err) {
      toast(errorText(err), "err");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section id="tab-check">
      <div className="check-page">
        <div>
          <div className="hero">
            <h1>Проверьте формулировку цели</h1>
            <textarea id="goalInput" aria-label="Формулировка цели" value={goal} onChange={(e) => setGoal(e.target.value)}
              placeholder="Например: снизить долю просроченных заявок до 5% к 31.12.2025 в рамках проекта «Альфа»" />
            <div className="row wrap" style={{ marginTop: 14 }}>
              <Select id="departmentInput" ariaLabel="Подразделение" className="pill" value={departmentId}
                style={{ width: 320 }} onChange={(next) => { setDepartmentId(next); setResult(null); }}
                options={[{ value: "", label: "Подразделение не указано" },
                  ...options.map((d) => ({ value: d.departmentId!, label: d.name || d.departmentId! }))]} />
              <button className="btn primary" disabled={busy} onClick={() => void run()}>
                {busy ? <><Spinner /> Проверяем…</> : "Проверить"}
              </button>
            </div>
            {!departmentId && (
              <div className="hint">Без подразделения применяются все правила, включая те, что действуют только в отдельных.</div>
            )}
          </div>

          {result && <Verdict result={result} onTrace={() => { setTrace(result); setSection("graph"); }} total={applicable.filter(({ rule }) => {
            const cell = departmentId ? cellState(rule, departmentId) : null;
            return !(cell?.kind === "exception" && cell.exception.status === "active");
          }).length} />}
          {result && (
            <details className="card pad" id="checkJson" open style={{ marginTop: 16 }}>
              <summary>Ответ API (JSON)</summary>
              <pre className="mono json">{JSON.stringify(result, null, 2)}</pre>
            </details>
          )}
        </div>

        <aside style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="card pad">
            <h3>Что проверяется{department ? ` для «${department.name || department.departmentId}»` : ""}</h3>
            <div className="small muted" style={{ margin: "4px 0 8px" }}>
              правил: {applicable.length}{skipped ? ` · не для этого подразделения: ${skipped}` : ""}
            </div>
            {applicable.map(({ rule }) => {
              // Утверждённое исключение: правило в подразделении не применяется вовсе.
              const cell = departmentId ? cellState(rule, departmentId) : null;
              const exempt = cell?.kind === "exception" && cell.exception.status === "active" ? cell.exception : null;
              const state = exempt || !result ? "skip" : failed.has(rule.ruleId ?? "") ? "bad" : "good";
              return (
                <div key={rule.nodeId} className="checkline">
                  <span className={`ico sm ${state}`}>{state === "bad" ? "✕" : state === "good" ? "✓" : "–"}</span>
                  <span className={exempt ? "dim" : ""}>
                    {rule.description}{exempt ? ` — не применяется (${exempt.basis})` : ""}
                  </span>
                </div>
              );
            })}
            {!applicable.length && <div className="dim">Правил нет — проверять нечего.</div>}
            <button className="btn sm ghost" style={{ margin: "6px 0 0 -8px" }} onClick={() => setSection("rules")}>Все правила →</button>
          </div>

          {(candidates > 0 || problems > 0) && (
            <div className="card pad">
              <h3>Нужно ваше решение</h3>
              {candidates > 0 && (
                <div className="todo" style={{ marginTop: 10 }}>
                  <div className="mid">Исключений ждут утверждения: {candidates}</div>
                  <button className="btn sm" onClick={() => setSection("rules")}>Открыть</button>
                  <div className="d">Договорённости подразделений, не закреплённые приказом</div>
                </div>
              )}
              {problems > 0 && (
                <div className="todo" style={candidates ? undefined : { marginTop: 10 }}>
                  <div className="mid">Замечаний к данным: {problems}</div>
                  <button className="btn sm" onClick={() => setSection("health")}>Открыть</button>
                  <div className="d">{health?.error ? "Есть ошибки: проверка может давать неверный результат" : "Проверка работает, но данные стоит поправить"}</div>
                </div>
              )}
            </div>
          )}

          <div className="card pad navy">
            <h3>Каталог</h3>
            <div className="row" style={{ marginTop: 10, gap: 22 }}>
              <div className="stat"><b>{orders.length}</b><span>приказов</span></div>
              <div className="stat"><b>{allRuleRefs(orders).length}</b><span>правил</span></div>
              <div className="stat"><b>{options.length}</b><span>подразделений</span></div>
            </div>
          </div>
        </aside>
      </div>
    </section>
  );
}

function Verdict({ result, total, onTrace }: { result: CheckResult; total: number; onTrace: () => void }) {
  const manual = result.status === "NEEDS_MANUAL_REVIEW";
  const bad = result.violations.length;
  return (
    <div className="card verdict" id="checkResult">
      <div className="row wrap" style={{ paddingBottom: 12 }}>
        {manual
          ? <span className="badge warn lg">Требуется ручная проверка</span>
          : bad ? <span className="badge err lg">Нужно доработать</span> : <span className="badge ok lg">Нарушений нет</span>}
        {!manual && <span className="muted">{bad ? `не выполнено правил: ${bad} из ${total}` : `проверено правил: ${total}`}</span>}
        <div className="spacer" />
        {!manual && <button className="btn sm" onClick={onTrace}>Показать на графе</button>}
        <span className="dim">подразделение: {result.department
          ? <Chip>{result.department.name || result.department.id}</Chip> : "не определено"}</span>
      </div>

      {result.notes.map((n, i) => <div key={i} className="alert" style={{ marginBottom: 8 }}>{n}</div>)}

      {result.violations.map((v, i) => {
        const examples = v.examples.filter((e): e is string => !!e);
        const duties = (v.matched_duties ?? []).filter((m) => m.duty);
        return (
          <div key={i} className="vitem violation">
            <span className="ico bad">✕</span>
            <div className="t">{v.rule_text}
              {v.candidate_exception && (
                <span className="badge warn" title={v.candidate_exception.note ?? undefined}>
                  есть исключение-кандидат — не утверждено
                </span>
              )}
            </div>
            <div className="d">{place(v)}</div>
            {(v.check_instruction || examples.length > 0 || duties.length > 0) && (
              <div className="fix">
                {duties.map((m, j) => (
                  <div key={"d" + j}><b>Совпадает с обязанностью{m.title ? ` (${m.title})` : ""}:</b> «{m.duty}»</div>
                ))}
                {v.check_instruction && <div><b>Как исправить:</b> {v.check_instruction}</div>}
                {examples.map((ex, j) => (
                  <div key={j}><b>{v.example_kind === "violation" ? "Так нельзя:" : "Пример:"}</b> «{ex}»</div>
                ))}
              </div>
            )}
          </div>
        );
      })}

      {result.exemptions.map((x, i) => (
        <div key={"x" + i} className="vitem exemption">
          <span className="ico skip">–</span>
          <div className="t">{x.rule_text} <span className="badge ok">не применяется в подразделении</span></div>
          <div className="d">{place(x)}</div>
          <div className="d">Основание: {x.basis || "не указано"}{x.note ? ` — ${x.note}` : ""}</div>
        </div>
      ))}

      {!manual && result.detected_attributes.length > 0 && (
        <div className="vitem">
          <span className="ico good">✓</span>
          <div className="t" style={{ fontSize: 14 }}>Найдено в цели</div>
          {result.detected_attributes.map((a) => (
            <div key={a} className="d chips">
              <Chip>{a}</Chip>
              {result.attribute_quotes?.[a] && <span className="quote">«{result.attribute_quotes[a]}»</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
