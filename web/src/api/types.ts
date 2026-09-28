/* Формы ответов API. Повторяют api/catalog.py и api/diagnostics.py:
   у эндпоинтов нет response_model, поэтому OpenAPI ответы не описывает
   и сгенерировать эти типы из него нельзя. Меняете ответ API — меняйте здесь. */

export type Status = "active" | "archived";
export type RuleType = "PROHIBITION" | "REQUIREMENT";

/** Любые свойства узла, кроме служебных, приходят как есть. */
type Extra = { [key: string]: unknown };

export interface Example extends Extra {
  nodeId: string;
  status: Status;
  exampleId?: string;
  text?: string;
  isViolation?: boolean;
}

export interface Rule extends Extra {
  nodeId: string;
  status: Status;
  ruleId?: string;
  type?: RuleType;
  description?: string;
  checkInstruction?: string;
  targets: string[];
  examples: Example[];
}

export interface ClauseRef {
  nodeId: string;
  code: string;
}

export interface Clause extends Extra {
  nodeId: string;
  status: Status;
  clauseId?: string;
  code?: string;
  text?: string;
  rules: Rule[];
  references: ClauseRef[];
}

export interface Order extends Extra {
  nodeId: string;
  status: Status;
  orderId?: string;
  number?: string;
  title?: string;
  date?: string;
  clauses: Clause[];
}

export interface CheckTarget extends Extra {
  nodeId: string;
  status: Status;
  name: string;
  description: string;
  rules: string[];
}

export interface FlatClause {
  nodeId: string;
  code: string;
  order_number: string;
  status: Status;
}

export interface NodeProps extends Extra {
  nodeId: string;
  labels: string[];
}

export interface Descendants {
  clauses: number;
  rules: number;
  examples: number;
}

export type NodeKind = "Order" | "Clause" | "Rule" | "ViolationExample" | "CheckTarget";

export interface IssueItem {
  label: string;
  nodeId?: string;
  kind?: NodeKind;
}

export interface Issue {
  code: string;
  severity: "error" | "warning" | "info";
  title: string;
  detail: string;
  items: IssueItem[];
  fix: { action: string; label: string } | null;
}

export interface Diagnostics {
  issues: Issue[];
  counts: { error: number; warning: number; info: number };
  check_targets: number;
  ready: boolean;
  problems: string[];
}

export interface RepairReport {
  orders: number;
  clauses: number;
  rules: number;
  examples: number;
  statuses: number;
}

export type CheckStatus = "ALLOWED" | "VIOLATIONS_FOUND" | "NEEDS_MANUAL_REVIEW";

export interface Violation {
  order_number: string | null;
  order_title: string | null;
  clause_code: string | null;
  clause_text: string | null;
  rule_id: string | null;
  rule_text: string | null;
  check_instruction: string | null;
  violation_type: "PROHIBITION" | "MISSING_REQUIREMENT";
  attribute: string;
  example_kind: "violation" | "correct";
  examples: (string | null)[];
}

export interface CheckResult {
  goal: string;
  status: CheckStatus;
  allowed: boolean;
  detected_attributes: string[];
  violations: Violation[];
  notes: string[];
}
