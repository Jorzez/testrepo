import { useState, type FormEvent } from "react";

import { api, type ScopeException } from "../api/client";
import type { Department, ExceptionStatus, Rule } from "../api/types";
import { useCatalog } from "../state/catalog";
import { Spinner } from "../ui/common";
import { Overlay, useDialogs } from "../ui/Dialogs";
import { errorText, useToast } from "../ui/Toasts";

/* Область действия правила по подразделениям.
     «Действует только в» — ограничивает правило перечисленными подразделениями;
       ничего не отмечено — правило действует для всех.
     «Не применяется в» — исключения. Утверждённому нужно основание (пункт
       приказа, который его вводит); без основания исключение остаётся
       кандидатом и в вердикте не участвует. */

interface ExceptionRow {
  id: number;
  departmentId: string;
  status: ExceptionStatus;
  basis: string;
  note: string;
}

const STATUS_OPTIONS: { value: ExceptionStatus; label: string }[] = [
  { value: "candidate", label: "кандидат" },
  { value: "active", label: "действует" },
];

let rowId = 0;

export function useRuleScopeEditor() {
  const { openCustom } = useDialogs();
  return (rule: Rule) => openCustom((close) => <RuleScopeDialog rule={rule} close={close} />);
}

const title = (d: Department) => `${d.name || "(без названия)"} · ${d.departmentId ?? "нет идентификатора"}`;

function RuleScopeDialog({ rule, close }: { rule: Rule; close: () => void }) {
  const toast = useToast();
  const { departments, mutate } = useCatalog();
  // Подразделение без идентификатора выбрать нельзя: связь строится по departmentId.
  const options = departments.filter((d) => d.departmentId);
  const [only, setOnly] = useState<string[]>(() => rule.onlyIn.map((d) => d.departmentId));
  const [rows, setRows] = useState<ExceptionRow[]>(() => rule.exceptions.map((e) => ({
    id: ++rowId, departmentId: e.departmentId, status: e.status === "active" ? "active" : "candidate",
    basis: e.basis ?? "", note: e.note ?? "",
  })));
  const [busy, setBusy] = useState(false);
  const update = (id: number, patch: Partial<ExceptionRow>) =>
    setRows((list) => list.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  const used = new Set(rows.map((r) => r.departmentId));
  const free = options.filter((d) => !used.has(d.departmentId!) && !only.includes(d.departmentId!));

  async function submit(e: FormEvent) {
    e.preventDefault();
    const exceptions: ScopeException[] = [];
    for (const row of rows) {
      const basis = row.basis.trim();
      if (row.status === "active" && !basis) {
        toast(`Исключению для ${row.departmentId} нужно основание — пункт приказа. `
          + "Без него оно может быть только кандидатом.", "err");
        return;
      }
      exceptions.push({ departmentId: row.departmentId, status: row.status,
        basis: basis || null, note: row.note.trim() || null });
    }
    setBusy(true);
    try {
      await mutate(() => api.setRuleScope(rule.nodeId, only, exceptions), "Область действия обновлена");
      close();
    } catch (err) {
      toast(errorText(err), "err");
      setBusy(false);
    }
  }

  return (
    <Overlay onClose={close}>
      <form className="modal wide" onSubmit={submit}>
        <h3>Подразделения правила {rule.ruleId}</h3>
        <div className="content">
          {!options.length && (
            <div className="dim" style={{ marginBottom: 12 }}>
              Подразделений нет — заведите их на вкладке «Подразделения».
            </div>
          )}
          <div className="field">
            <label>Действует только в</label>
            <div className="optlist" id="scopeOnly">
              {options.map((d) => {
                const id = d.departmentId!;
                return (
                  <label key={id}>
                    <input type="checkbox" checked={only.includes(id)} disabled={used.has(id)}
                      onChange={(e) => setOnly(e.target.checked ? [...only, id] : only.filter((x) => x !== id))} />
                    <span>{title(d)}{used.has(id) && <span className="d"> — уже в исключениях</span>}</span>
                  </label>
                );
              })}
            </div>
            <div className="hint">Ничего не отмечено — правило действует для всех подразделений.</div>
          </div>

          <div className="field">
            <label>Не применяется в</label>
            {rows.map((row) => (
              <div key={row.id} className="scope-row" data-exception={row.departmentId}>
                <select aria-label="Подразделение" value={row.departmentId}
                  onChange={(e) => update(row.id, { departmentId: e.target.value })}>
                  {options.filter((d) => d.departmentId === row.departmentId || free.includes(d))
                    .map((d) => <option key={d.departmentId} value={d.departmentId}>{title(d)}</option>)}
                </select>
                <select aria-label="Статус исключения" value={row.status}
                  onChange={(e) => update(row.id, { status: e.target.value as ExceptionStatus })}>
                  {STATUS_OPTIONS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                </select>
                <input type="text" aria-label="Основание" value={row.basis} placeholder="пункт приказа, напр. ПР-01 п. 4.2"
                  onChange={(e) => update(row.id, { basis: e.target.value })} />
                <button type="button" className="btn sm ghost" title="Убрать исключение"
                  onClick={() => setRows((list) => list.filter((r) => r.id !== row.id))}>✕</button>
                <input type="text" aria-label="Примечание" className="scope-note" value={row.note}
                  placeholder="примечание: откуда договорённость"
                  onChange={(e) => update(row.id, { note: e.target.value })} />
              </div>
            ))}
            <button type="button" className="btn sm" disabled={!free.length}
              onClick={() => setRows((list) => [...list, {
                id: ++rowId, departmentId: free[0].departmentId!, status: "candidate", basis: "", note: "",
              }])}>
              + Исключение
            </button>
            <div className="hint">
              Кандидат — договорённость, не утверждённая владельцем приказа: в вердикте не участвует,
              нарушение остаётся и помечается в ответе. Чтобы исключение действовало, укажите
              пункт приказа, который его вводит, и статус «действует» — основание попадёт в ответ проверки.
            </div>
          </div>
        </div>
        <div className="foot">
          <button type="button" className="btn" onClick={close}>Отмена</button>
          <button type="submit" className="btn primary" disabled={busy}>
            {busy ? <><Spinner /> Сохранение…</> : "Сохранить"}
          </button>
        </div>
      </form>
    </Overlay>
  );
}
