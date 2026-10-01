import type { ScopeException } from "../api/client";
import type { Rule, RuleException } from "../api/types";

/* Область действия правила по подразделениям — чистые функции для матрицы
   и панели правила. Правила те же, что в графе (api/graph.py):
     нет списка «только в»        — правило действует для всех;
     подразделение вне списка     — правило на него не распространяется;
     исключение                   — действует, но не применяется (active)
                                    или ждёт утверждения (candidate).
   Исключение имеет смысл только там, где правило действует, поэтому при
   заданном списке «только в» оно всегда внутри списка. */

export interface Scope {
  only: string[];
  exceptions: ScopeException[];
}

export type CellState =
  | { kind: "applies" }
  | { kind: "off" }
  | { kind: "exception"; exception: RuleException };

export function cellState(rule: Rule, departmentId: string): CellState {
  if (rule.onlyIn.length && !rule.onlyIn.some((d) => d.departmentId === departmentId)) return { kind: "off" };
  const exception = rule.exceptions.find((e) => e.departmentId === departmentId);
  return exception ? { kind: "exception", exception } : { kind: "applies" };
}

export const scopeOf = (rule: Rule): Scope => ({
  only: rule.onlyIn.map((d) => d.departmentId),
  exceptions: rule.exceptions.map((e) => ({
    departmentId: e.departmentId,
    // Неизвестный статус не снимает нарушение — в редакторе это кандидат.
    status: e.status === "active" && e.basis ? "active" : "candidate",
    basis: e.basis, note: e.note,
  })),
});

const without = (scope: Scope, id: string): ScopeException[] =>
  scope.exceptions.filter((e) => e.departmentId !== id);

/** Правило действует в подразделении. */
export const withApplies = (scope: Scope, id: string): Scope => ({
  only: scope.only.length && !scope.only.includes(id) ? [...scope.only, id] : scope.only,
  exceptions: without(scope, id),
});

/** Правило на подразделение не распространяется. null — если так правило
    перестало бы действовать где-либо: пустой список означает «для всех». */
export function withOff(scope: Scope, id: string, allIds: string[]): Scope | null {
  const only = (scope.only.length ? scope.only : allIds).filter((d) => d !== id);
  if (!only.length) return null;
  return { only, exceptions: without(scope, id).filter((e) => only.includes(e.departmentId)) };
}

/** Правило действует, но в подразделении не применяется. */
export const withException = (scope: Scope, exception: ScopeException): Scope => ({
  only: scope.only.length && !scope.only.includes(exception.departmentId)
    ? [...scope.only, exception.departmentId] : scope.only,
  exceptions: [...without(scope, exception.departmentId), exception],
});

/** Короткое описание области действия — для карточек и сводок. */
export function scopeSummary(rule: Rule): string {
  const name = (d: { name: string | null; departmentId: string }) => d.name || d.departmentId;
  const base = rule.onlyIn.length ? "Только: " + rule.onlyIn.map(name).join(", ") : "Все подразделения";
  const active = rule.exceptions.filter((e) => e.status === "active");
  return active.length ? `${base}, кроме ${active.map(name).join(", ")}` : base;
}
