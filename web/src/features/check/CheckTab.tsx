import { useState } from "react";

import { api } from "../../api/client";
import type { CheckResult, CheckStatus } from "../../api/types";
import { useCatalog } from "../../state/catalog";
import { Chip, Spinner } from "../../ui/common";
import { errorText, useToast } from "../../ui/Toasts";

/* Прогон формулировки через /check-goal с разбором нарушений. Подразделение
   необязательно: без него применяются все правила, а причина попадает в заметки. */

const STATUS_VIEW: Record<CheckStatus, { text: string; cls: string }> = {
  ALLOWED: { text: "Нарушений нет", cls: "ok" },
  VIOLATIONS_FOUND: { text: "Найдены нарушения", cls: "warn" },
  NEEDS_MANUAL_REVIEW: { text: "Требуется ручная проверка", cls: "warn" },
};

export function CheckTab({ hidden }: { hidden: boolean }) {
  const toast = useToast();
  const { departments } = useCatalog();
  const [goal, setGoal] = useState("");
  const [departmentId, setDepartmentId] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<CheckResult | null>(null);

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
    <section id="tab-check" className={hidden ? "hidden" : ""}>
      <div className="panel">
        <div className="field">
          <label htmlFor="goalInput">Формулировка цели</label>
          <textarea id="goalInput" value={goal} onChange={(e) => setGoal(e.target.value)}
            placeholder="Например: снизить долю просроченных заявок до 5% к 31.12.2025 в рамках проекта «Альфа»" />
        </div>
        <div className="field">
          <label htmlFor="departmentInput">Подразделение</label>
          <select id="departmentInput" value={departmentId} onChange={(e) => setDepartmentId(e.target.value)}>
            <option value="">не указано — применяются все правила</option>
            {departments.filter((d) => d.departmentId && d.status === "active").map((d) => (
              <option key={d.departmentId} value={d.departmentId}>{d.name} · {d.departmentId}</option>
            ))}
          </select>
        </div>
        <button className="btn primary" disabled={busy} onClick={run}>
          {busy ? <><Spinner /> Проверяем…</> : "Проверить"}
        </button>
      </div>
      {result && <Result result={result} />}
    </section>
  );
}

function Result({ result }: { result: CheckResult }) {
  const view = STATUS_VIEW[result.status] ?? { text: result.status, cls: "archived" };
  return (
    <div className="panel" id="checkResult" style={{ marginTop: 16 }}>
      <div className="row" style={{ alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span className={`badge ${view.cls}`}>{view.text}</span>
        <span className="dim">подразделение: {result.department
          ? <Chip>{result.department.name || result.department.id}</Chip>
          : "не определено"}</span>
        <span className="dim">атрибуты в цели:{" "}
          {result.detected_attributes.length
            ? result.detected_attributes.map((a) => <Chip key={a}>{a}</Chip>)
            : "не найдены"}
        </span>
      </div>
      {result.notes.length > 0 && (
        <div style={{ marginTop: 12 }}>
          {result.notes.map((n, i) => (
            <div key={i} className="badge warn" style={{ display: "block", marginTop: 6, whiteSpace: "normal" }}>{n}</div>
          ))}
        </div>
      )}
      {result.violations.map((v, i) => {
        const prohibition = v.violation_type === "PROHIBITION";
        const examples = v.examples.filter((e): e is string => !!e);
        const bad = v.example_kind === "violation";
        return (
          <div key={i} className="violation">
            <div className="rule-meta">
              <span className={`badge ${prohibition ? "prohibition" : "requirement"}`}>
                {prohibition ? "Запрет нарушен" : "Требование не выполнено"}
              </span>
              <span className="mono">{v.order_number} {v.clause_code}</span>
              <Chip>{v.attribute}</Chip>
              {v.candidate_exception && (
                <span className="badge warn" title={v.candidate_exception.note ?? undefined}>
                  есть исключение-кандидат — не утверждено
                </span>
              )}
            </div>
            <div>{v.rule_text}</div>
            {v.check_instruction && <div className="dim" style={{ marginTop: 6 }}>{v.check_instruction}</div>}
            {examples.length > 0 && (
              <div className="examples">
                {examples.map((ex, j) => (
                  <div key={j} className={`example ${bad ? "bad" : "good"}`}>
                    <span className="mark">{bad ? "✗" : "✓"}</span><span>{ex}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
      {result.exemptions.map((x, i) => (
        <div key={"x" + i} className="exemption">
          <div className="rule-meta">
            <span className="badge ok">Не применяется в подразделении</span>
            <span className="mono">{x.order_number} {x.clause_code}</span>
            <Chip>{x.attribute}</Chip>
          </div>
          <div>{x.rule_text}</div>
          <div className="dim" style={{ marginTop: 6 }}>
            Основание: {x.basis || "не указано"}{x.note ? ` — ${x.note}` : ""}
          </div>
        </div>
      ))}
    </div>
  );
}
