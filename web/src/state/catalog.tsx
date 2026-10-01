import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode,
} from "react";

import { api } from "../api/client";
import type { CheckTarget, Department, Diagnostics, FlatClause, NodeKind, Order } from "../api/types";
import { errorText, useToast } from "../ui/Toasts";
import { findOrderOf } from "./tree";

export type Tab = "catalog" | "targets" | "departments" | "check" | "health";
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

interface CatalogState extends Data, Flags {
  apiState: ApiState;
  health: Diagnostics["counts"] | null;
  tab: Tab;
  setTab: (tab: Tab) => void;
  /** Перечитать данные; флаги архива можно поменять тем же вызовом. */
  reload: (flags?: Partial<Flags>) => Promise<Data | null>;
  /** Выполнить изменение, показать сообщение и перечитать данные. */
  mutate: (fn: () => Promise<unknown>, success?: string) => Promise<void>;
  refreshHealth: () => Promise<void>;
  openOrders: Set<string>;
  openClauses: Set<string>;
  toggleOrder: (id: string) => void;
  toggleClause: (id: string) => void;
  expand: (orderIds: string[], clauseIds: string[]) => void;
  collapseAll: () => void;
  goToNode: (nodeId: string, kind?: NodeKind) => Promise<void>;
}

const Context = createContext<CatalogState | null>(null);

export function useCatalog() {
  const ctx = useContext(Context);
  if (!ctx) throw new Error("useCatalog вне CatalogProvider");
  return ctx;
}

const toggled = (set: Set<string>, id: string) => {
  const next = new Set(set);
  if (next.has(id)) next.delete(id); else next.add(id);
  return next;
};

export function CatalogProvider({ children }: { children: ReactNode }) {
  const toast = useToast();
  const [data, setData] = useState<Data>({ orders: [], targets: [], clauses: [], departments: [] });
  const [flags, setFlags] = useState<Flags>({
    showArchived: false, showArchivedTargets: false, showArchivedDepartments: false,
  });
  const flagsRef = useRef(flags);
  const [apiState, setApiState] = useState<ApiState>("connecting");
  const [health, setHealth] = useState<Diagnostics["counts"] | null>(null);
  const [tab, setTab] = useState<Tab>("catalog");
  const [openOrders, setOpenOrders] = useState<Set<string>>(new Set());
  const [openClauses, setOpenClauses] = useState<Set<string>>(new Set());
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

  const goToNode = useCallback(async (nodeId: string, kind?: NodeKind) => {
    if (kind === "CheckTarget") {
      setTab("targets");
      if (!data.targets.some((t) => t.nodeId === nodeId) && !flagsRef.current.showArchivedTargets)
        await reload({ showArchivedTargets: true });
      setFlashTarget({ id: nodeId, seq: Date.now() });
      return;
    }
    if (kind === "Department") {
      setTab("departments");
      if (!data.departments.some((d) => d.nodeId === nodeId) && !flagsRef.current.showArchivedDepartments)
        await reload({ showArchivedDepartments: true });
      setFlashTarget({ id: nodeId, seq: Date.now() });
      return;
    }
    setTab("catalog");
    let orders = data.orders;
    let found = findOrderOf(orders, nodeId);
    if (!found && !flagsRef.current.showArchived) {
      orders = (await reload({ showArchived: true }))?.orders ?? orders;
      found = findOrderOf(orders, nodeId);
    }
    if (found) {
      setOpenOrders((s) => new Set(s).add(found.order.nodeId));
      // Пункты свёрнуты по умолчанию — раскрываем тот, внутри которого искомый узел.
      if (found.clause) setOpenClauses((s) => new Set(s).add(found.clause!.nodeId));
    }
    setFlashTarget({ id: nodeId, seq: Date.now() });
  }, [data, reload]);

  // Подсветка — после того как React отрисовал раскрытые узлы.
  useEffect(() => {
    if (!flashTarget) return;
    const el = document.querySelector(`[data-node="${CSS.escape(flashTarget.id)}"]`);
    setFlashTarget(null);
    if (!el) { toast("Объект не найден в текущем представлении", "err"); return; }
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.remove("flash");
    void (el as HTMLElement).offsetWidth;
    el.classList.add("flash");
  }, [flashTarget, toast]);

  const value = useMemo<CatalogState>(() => ({
    ...data, ...flags, apiState, health, tab, setTab, reload, mutate, refreshHealth,
    openOrders, openClauses,
    toggleOrder: (id) => setOpenOrders((s) => toggled(s, id)),
    toggleClause: (id) => setOpenClauses((s) => toggled(s, id)),
    expand: (orderIds, clauseIds) => {
      setOpenOrders((s) => new Set([...s, ...orderIds]));
      setOpenClauses((s) => new Set([...s, ...clauseIds]));
    },
    collapseAll: () => { setOpenOrders(new Set()); setOpenClauses(new Set()); },
    goToNode,
  }), [data, flags, apiState, health, tab, reload, mutate, refreshHealth, openOrders, openClauses, goToNode]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}
