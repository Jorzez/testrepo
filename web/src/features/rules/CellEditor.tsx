import { useLayoutEffect, useRef, useState } from "react";

import { api } from "../../api/client";
import type { Department, ExceptionStatus, Rule } from "../../api/types";
import { useCatalog } from "../../state/catalog";
import { cellState, scopeOf, withApplies, withException, withOff, type Scope } from "../../state/scope";
import { Spinner } from "../../ui/common";
import { Overlay, useDialogs } from "../../ui/Dialogs";
import { errorText, useToast } from "../../ui/Toasts";

/* Решение по одной ячейке матрицы: как правило относится к подразделению.
   Три состояния: действует, не распространяется, исключение. Исключение без
   пункта приказа остаётся кандидатом и в вердикте не участвует. */

type Mode = "applies" | "off" | "exception";

interface Props {
  rule: Rule;
  /** Не задано — подразделение выбирается в самом окне (новое исключение). */
  department?: Department;
  /** Ячейка, у которой открыть окно; без неё окно по центру. */
  anchor?: DOMRect;
  close: () => void;
}

export function useCellEditor() {
  const { openCustom } = useDialogs();
  return (props: Omit<Props, "close">) => openCustom((close) => <CellEditor {...props} close={close} />);
}

const name = (d: Department) => d.name || d.departmentId || "";

function CellEditor({ rule, department, anchor, close }: Props) {
  const toast = useToast();
  const { departments, mutate } = useCatalog();
  const known = departments.filter((d) => d.departmentId);
  // Новое исключение можно завести только там, где правило сейчас действует.
  const free = known.filter((d) => cellState(rule, d.departmentId!).kind === "applies");
  const [departmentId, setDepartmentId] = useState(department?.departmentId ?? free[0]?.departmentId ?? "");
  const current = department ? cellState(rule, departmentId) : { kind: "exception" as const, exception: null };
  const [mode, setMode] = useState<Mode>(current.kind);
  const [basis, setBasis] = useState(current.kind === "exception" ? current.exception?.basis ?? "" : "");
  const [note, setNote] = useState(current.kind === "exception" ? current.exception?.note ?? "" : "");
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);

  // Окно — под ячейкой; если не помещается, поднимается, чтобы остаться на экране.
  useLayoutEffect(() => {
    if (!anchor || !ref.current) return;
    const { offsetWidth: w, offsetHeight: h } = ref.current;
    setPos({
      left: Math.max(12, Math.min(anchor.left + anchor.width / 2 - w / 2, innerWidth - w - 12)),
      top: Math.max(12, Math.min(anchor.bottom + 8, innerHeight - h - 12)),
    });
  }, [anchor, mode]);

  async function save(status?: ExceptionStatus) {
    const scope = scopeOf(rule);
    let next: Scope | null;
    if (mode === "applies") next = withApplies(scope, departmentId);
    else if (mode === "off") {
      next = withOff(scope, departmentId, known.map((d) => d.departmentId!));
      if (!next) {
        toast("Правило должно действовать хотя бы в одном подразделении. Если оно больше не нужно — отправьте его в архив.", "err");
        return;
      }
    } else {
      if (!departmentId) { toast("Выберите подразделение", "err"); return; }
      if (status === "active" && !basis.trim()) {
        toast("Чтобы утвердить исключение, укажите пункт приказа, который его вводит.", "err");
        return;
      }
      next = withException(scope, {
        departmentId, status: status ?? "candidate", basis: basis.trim() || null, note: note.trim() || null,
      });
    }
    const scopeToSave = next;
    setBusy(true);
    try {
      await mutate(() => api.setRuleScope(rule.nodeId, scopeToSave.only, scopeToSave.exceptions),
        "Область действия обновлена");
      close();
    } catch (err) {
      toast(errorText(err), "err");
      setBusy(false);
    }
  }

  const option = (value: Mode, title: string, detail?: string) => (
    <button type="button" role="radio" aria-checked={mode === value} className="opt" onClick={() => setMode(value)}>
      <i /><span className="t">{title}</span>
      {detail && <span className="d">{detail}</span>}
    </button>
  );

  const body = (
    <div ref={ref} role="dialog" aria-label="Решение по ячейке"
      className={anchor ? "pop" : "modal"} style={anchor ? pos ?? { left: -9999, top: -9999 } : { padding: "18px 20px", width: 420 }}>
      <div className="small dim">{rule.description}</div>
      {department
        ? <h2 style={{ fontSize: 17, marginTop: 2 }}>{name(department)}</h2>
        : (
          <div className="field" style={{ marginTop: 8 }}>
            <label htmlFor="cellDepartment">Подразделение</label>
            <select id="cellDepartment" value={departmentId} onChange={(e) => setDepartmentId(e.target.value)}>
              {free.map((d) => <option key={d.departmentId} value={d.departmentId}>{name(d)}</option>)}
            </select>
          </div>
        )}

      {department && (
        <div role="radiogroup">
          {option("applies", "Правило действует")}
          {option("off", "Не действует", "Приказ не распространяет правило на это подразделение")}
          {option("exception", "Исключение", "Действует, но здесь не применяется — по пункту приказа или договорённости")}
        </div>
      )}

      {mode === "exception" && (
        <>
          <div className="field" style={{ marginTop: 12 }}>
            <label htmlFor="cellBasis">Основание — пункт приказа</label>
            <input id="cellBasis" type="text" value={basis} placeholder="например, ПР-01 п. 2.6"
              onChange={(e) => setBasis(e.target.value)} />
            <div className="hint">Без пункта приказа исключение остаётся кандидатом: нарушение не снимается.</div>
          </div>
          <div className="field">
            <label htmlFor="cellNote">Откуда договорённость</label>
            <input id="cellNote" type="text" value={note} placeholder="необязательно"
              onChange={(e) => setNote(e.target.value)} />
          </div>
        </>
      )}

      <div className="row" style={{ marginTop: 14, justifyContent: "flex-end" }}>
        <button className="btn sm ghost" onClick={close}>Отмена</button>
        {mode === "exception" ? (
          <>
            <button className="btn sm" disabled={busy || !departmentId} onClick={() => void save("candidate")}>
              Оставить кандидатом
            </button>
            <button className="btn sm primary" disabled={busy || !departmentId} onClick={() => void save("active")}>
              {busy ? <Spinner /> : "Утвердить"}
            </button>
          </>
        ) : (
          <button className="btn sm primary" disabled={busy} onClick={() => void save()}>
            {busy ? <Spinner /> : "Сохранить"}
          </button>
        )}
      </div>
    </div>
  );

  return <Overlay clear={!!anchor} onClose={close}>{body}</Overlay>;
}
