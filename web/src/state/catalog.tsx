import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode,
} from "react";

import { api } from "../api/client";
import type { CheckTarget, Department, Diagnostics, FlatClause, NodeKind, Order } from "../api/types";
import { errorText, useToast } from "../ui/Toasts";
import { findOrderOf, findRuleRef } from "./tree";

export type Section = "check" | "rules" | "orders" | "departments" | "targets" | "health" | "users";
export type ApiState = "connecting" | "online" | "offline";

interface Data {
  orders: Order[];
  targets: CheckTarget[];
  clauses: FlatClause[];
  departments: Department[];
}

interface Flags {
  showArchived: boolean;
  showArchivedTargets: boolean;
  showArchivedDepartments: boolean;
}

/** С чего начать мастер нового правила. */
export interface WizardPreset {
  orderNodeId?: string;
  clauseNodeId?: string;
}

interface CatalogState extends Data, Flags {
  apiState: ApiState;
  health: Diagnostics["counts"] | null;
  section: Section;
  setSection: (section: Section) => void;
  /** Перечитать данные; флаги архива можно поменять тем же вызовом. */
  reload: (flags?: Partial<Flags>) => Promise<Data | null>;
  /** Выполнить изменение, показать сообщение и перечитать данные. */
  mutate: (fn: () => Promise<unknown>, success?: string) => Promise<void>;
  refreshHealth: () => Promise<void>;
  /** Приказ, открытый в разделе «Приказы». */
  selectedOrder: string | null;
  selectOrder: (nodeId: string) => void;
  /** Правило, открытое в боковой панели. */
  panelRule: string | null;
  openRule: (nodeId: string) => void;
  closeRule: () => void;
  wizard: WizardPreset | null;
  openWizard: (preset?: WizardPreset) => void;
  closeWizard: () => void;
  goToNode: (nodeId: string, kind?: NodeKind) => Promise<void>;
}

const Context = createContext<CatalogState | null>(null);

export function useCatalog() {
  const ctx = useContext(Context);
  if (!ctx) throw new Error("useCatalog вне CatalogProvider");
  return ctx;
}

export function CatalogProvider({ children }: { children: ReactNode }) {
  const toast = useToast();
  const [data, setData] = useState<Data>({ orders: [], targets: [], clauses: [], departments: [] });
  const [flags, setFlags] = useState<Flags>({
    showArchived: false, showArchivedTargets: false, showArchivedDepartments: false,
  });
  const flagsRef = useRef(flags);
  const [apiState, setApiState] = useState<ApiState>("connecting");
  const [health, setHealth] = useState<Diagnostics["counts"] | null>(null);
  const [section, setSectionState] = useState<Section>("check");
  const [selectedOrder, setSelectedOrder] = useState<string | null>(null);
  const [panelRule, setPanelRule] = useState<string | null>(null);
  const [wizard, setWizard] = useState<WizardPreset | null>(null);
  const [flashTarget, setFlashTarget] = useState<{ id: string; seq: number } | null>(null);

  const refreshHealth = useCallback(async () => {
    try { setHealth((await api.diagnostics()).counts); } catch { /* значок необязателен */ }
  }, []);

  const reload = useCallback(async (override?: Partial<Flags>) => {
    const next = { ...flagsRef.current, ...override };
    flagsRef.current = next;
    setFlags(next);
    let loaded: Data | null = null;
    try {
      const [tree, targets, clauses, departments] = await Promise.all([
        api.tree(next.showArchived), api.checkTargets(next.showArchivedTargets), api.clauses(),
        api.departments(next.showArchivedDepartments),
      ]);
      loaded = {
        orders: tree.orders, targets: targets.targets, clauses: clauses.clauses,
        departments: departments.departments,
      };
      setData(loaded);
      setApiState("online");
    } catch (err) {
      setApiState("offline");
      toast("Не удалось получить данные: " + errorText(err), "err");
    }
    void refreshHealth();
    return loaded;
  }, [toast, refreshHealth]);

  const mutate = useCallback(async (fn: () => Promise<unknown>, success?: string) => {
    await fn();
    if (success) toast(success, "ok");
    await reload();
  }, [toast, reload]);

  useEffect(() => { void reload(); }, [reload]);

  // Панель правила и мастер живут только в «Правилах» и «Приказах».
  const setSection = useCallback((next: Section) => {
    setSectionState(next);
    setWizard(null);
    if (next !== "rules" && next !== "orders") setPanelRule(null);
  }, []);

  const goToNode = useCallback(async (nodeId: string, kind?: NodeKind) => {
    const flash = () => setFlashTarget({ id: nodeId, seq: Date.now() });

    if (kind === "CheckTarget" || kind === "Department") {
      const [list, flag]: [{ nodeId: string }[], keyof Flags] = kind === "CheckTarget"
        ? [data.targets, "showArchivedTargets"] : [data.departments, "showArchivedDepartments"];
      setSection(kind === "CheckTarget" ? "targets" : "departments");
      if (!list.some((n) => n.nodeId === nodeId) && !flagsRef.current[flag]) await reload({ [flag]: true });
      flash();
      return;
    }

    let orders = data.orders;
    if (!findOrderOf(orders, nodeId) && !flagsRef.current.showArchived)
      orders = (await reload({ showArchived: true }))?.orders ?? orders;
    const found = findOrderOf(orders, nodeId);
    setSection("orders");
    if (found) setSelectedOrder(found.order.nodeId);
    // Правило и его примеры открываются в панели — там видно всё сразу.
    const rule = findRuleRef(orders, nodeId);
    setPanelRule(rule ? rule.rule.nodeId : null);
    flash();
  }, [data, reload, setSection]);

  // Подсветка — после того как React отрисовал нужный раздел.
  useEffect(() => {
    if (!flashTarget) return;
    // Узел может быть отрисован и в скрытом разделе — подсвечиваем видимый.
    const el = [...document.querySelectorAll<HTMLElement>(`[data-node="${CSS.escape(flashTarget.id)}"]`)]
      .find((node) => node.offsetParent !== null);
    setFlashTarget(null);
    if (!el) { toast("Объект не найден в текущем представлении", "err"); return; }
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.remove("flash");
    void el.offsetWidth;
    el.classList.add("flash");
  }, [flashTarget, toast]);

  const value = useMemo<CatalogState>(() => ({
    ...data, ...flags, apiState, health, section, setSection, reload, mutate, refreshHealth,
    selectedOrder, selectOrder: setSelectedOrder,
    panelRule, openRule: setPanelRule, closeRule: () => setPanelRule(null),
    wizard,
    openWizard: (preset) => { setSectionState("rules"); setPanelRule(null); setWizard(preset ?? {}); },
    closeWizard: () => setWizard(null),
    goToNode,
  }), [data, flags, apiState, health, section, setSection, reload, mutate, refreshHealth,
    selectedOrder, panelRule, wizard, goToNode]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}
