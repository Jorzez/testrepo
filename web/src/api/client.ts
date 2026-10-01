import type {
  CheckResult, CheckTarget, Department, Descendants, Diagnostics, ExceptionStatus, FlatClause,
  NodeProps, Order, RepairReport, RuleType, Status,
} from "./types";

/* Адрес API. По умолчанию тот же хост, порт 8080 — работает и локально,
   и через SSH-туннель. Переопределяется через ?api=http://host:port.
   В режиме разработки — относительный /api (прокси или фейк, см. vite.config.ts). */
export const API_BASE =
  new URLSearchParams(location.search).get("api")
  || (import.meta.env.DEV ? "/api" : `${location.protocol}//${location.hostname}:8080`);

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

type Method = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

async function request<T>(method: Method, path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(API_BASE + path, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("API недоступен", 0);
  }

  let payload: unknown = null;
  try { payload = await response.json(); } catch { /* пустой ответ */ }

  if (!response.ok) {
    const detail = (payload as { detail?: unknown } | null)?.detail;
    const message = typeof detail === "string" ? detail
      : Array.isArray(detail) ? detail.map((d) => d?.msg ?? JSON.stringify(d)).join("; ")
      : `HTTP ${response.status}`;
    throw new ApiError(message, response.status);
  }
  return payload as T;
}

/** Ответ создания узла: его свойства и nodeId. */
export interface Created {
  nodeId: string;
  [key: string]: unknown;
}

const enc = encodeURIComponent;
const node = (id: string) => `/catalog/nodes/${enc(id)}`;

export interface ScopeException {
  departmentId: string;
  status: ExceptionStatus;
  basis: string | null;
  note: string | null;
}

export const api = {
  tree: (includeArchived: boolean) =>
    request<{ orders: Order[] }>("GET", `/catalog/tree?include_archived=${includeArchived}`),
  checkTargets: (includeArchived: boolean) =>
    request<{ targets: CheckTarget[] }>("GET", `/catalog/check-targets?include_archived=${includeArchived}`),
  clauses: () => request<{ clauses: FlatClause[] }>("GET", "/catalog/clauses"),
  departments: (includeArchived: boolean) =>
    request<{ departments: Department[] }>("GET", `/catalog/departments?include_archived=${includeArchived}`),
  diagnostics: () => request<Diagnostics>("GET", "/catalog/diagnostics"),

  node: (id: string) => request<NodeProps>("GET", node(id)),
  patch: (id: string, properties: Record<string, unknown>) =>
    request<NodeProps>("PATCH", `${node(id)}/properties`, { properties }),
  setStatus: (id: string, status: Status) => request("POST", `${node(id)}/status`, { status }),
  descendants: (id: string) => request<Descendants>("GET", `${node(id)}/descendants`),
  remove: (id: string, force = false) => request("DELETE", node(id) + (force ? "?force=true" : "")),

  createOrder: (body: { number: string; title: string; date: string | null; orderId: string | null }) =>
    request<Created>("POST", "/catalog/orders", body),
  createClause: (body: { orderNodeId: string; code: string; text: string }) =>
    request<Created>("POST", "/catalog/clauses", body),
  createRule: (body: {
    clauseNodeId: string; type: RuleType; description: string; checkInstruction: string; targets: string[];
  }) => request<Created>("POST", "/catalog/rules", body),
  createExample: (body: { ruleNodeId: string; text: string; isViolation: boolean }) =>
    request<Created>("POST", "/catalog/examples", body),
  createTarget: (body: { name: string; description: string }) =>
    request<Created>("POST", "/catalog/check-targets", body),

  createDepartment: (body: { departmentId: string; name: string }) =>
    request<Created>("POST", "/catalog/departments", body),

  setRuleScope: (id: string, only: string[], exceptions: ScopeException[]) =>
    request("PUT", `/catalog/rules/${enc(id)}/departments`, { only, exceptions }),
  setRuleTargets: (id: string, targets: string[]) =>
    request("PUT", `/catalog/rules/${enc(id)}/targets`, { targets }),
  setReferences: (id: string, references: string[]) =>
    request("PUT", `/catalog/clauses/${enc(id)}/references`, { references }),
  moveClause: (id: string, parentNodeId: string) =>
    request("POST", `/catalog/clauses/${enc(id)}/move`, { parentNodeId }),
  moveRule: (id: string, parentNodeId: string) =>
    request("POST", `/catalog/rules/${enc(id)}/move`, { parentNodeId }),
  repairIdentifiers: () => request<RepairReport>("POST", "/catalog/repair-identifiers"),

  checkGoal: (goal: string, departmentId: string | null) =>
    request<CheckResult>("POST", "/check-goal", { goal, department_id: departmentId }),
};
