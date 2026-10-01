import type { ReactNode } from "react";

import { API_BASE } from "./api/client";
import logo from "./assets/logo.png";
import { CheckView } from "./features/check/CheckView";
import { DepartmentsTab } from "./features/departments/DepartmentsTab";
import { HealthTab } from "./features/health/HealthTab";
import { OrdersView } from "./features/orders/OrdersView";
import { RulePanel } from "./features/rules/RulePanel";
import { RulesView } from "./features/rules/RulesView";
import { TargetsTab } from "./features/targets/TargetsTab";
import { useCatalog, type Section } from "./state/catalog";

const icon = (path: ReactNode) => (
  <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
    aria-hidden="true">{path}</svg>
);

const SECTIONS: { id: Section; label: string; icon: ReactNode }[] = [
  { id: "check", label: "Проверка цели", icon: icon(<path d="M4 10l4 4 8-9" />) },
  { id: "rules", label: "Правила", icon: icon(<path d="M3 3h14v14H3zM3 8h14M3 13h14M8 3v14M13 3v14" />) },
  { id: "orders", label: "Приказы", icon: icon(<path d="M5 2h8l3 3v13H5zM8 8h6M8 12h6" />) },
  { id: "departments", label: "Подразделения", icon: icon(<><circle cx="10" cy="7" r="3" /><path d="M4 17c0-3 3-5 6-5s6 2 6 5" /></>) },
  { id: "targets", label: "Атрибуты", icon: icon(<path d="M3 5h9l5 5-5 5H3zM7 10h.01" />) },
  { id: "health", label: "Замечания", icon: icon(<path d="M10 3l8 14H2zM10 8v4M10 14.5v.5" />) },
];

const API_STATE = {
  connecting: { cls: "archived", text: "подключение…" },
  online: { cls: "ok", text: "API на связи" },
  offline: { cls: "warn", text: "API недоступен" },
};

export function App() {
  const { section, setSection, apiState, health, reload, panelRule, wizard } = useCatalog();
  const pill = API_STATE[apiState];
  // На значке — число ошибок, а если их нет, то предупреждений.
  const badge = health?.error || health?.warning || 0;
  const withPanel = !!panelRule && !wizard && (section === "rules" || section === "orders");

  return (
    <div className={`shell ${withPanel ? "with-panel" : ""}`}>
      <aside className="side">
        <div className="brand">
          <img src={logo} alt="" />
          <div>Проверка целей<small>каталог требований</small></div>
        </div>
        <nav role="tablist" aria-orientation="vertical">
          {SECTIONS.map((s) => (
            <button key={s.id} role="tab" className="nav-item" aria-selected={section === s.id} onClick={() => setSection(s.id)}>
              {s.icon}{s.label}
              {s.id === "health" && badge > 0 && <span className={`n ${health?.error ? "err" : "warn"}`}>{badge}</span>}
            </button>
          ))}
        </nav>
        <div className="spacer" />
        <div className="side-foot">
          <span className={`badge ${pill.cls}`}><span className="dot" />{pill.text}</span>
          <button className="btn sm" onClick={() => void reload()}>Обновить</button>
          <span className="api-base">{API_BASE}</span>
        </div>
      </aside>

      {/* Разделы не размонтируются: введённая цель и фильтры сохраняются при переключении. */}
      <main className="main">
        <CheckView hidden={section !== "check"} />
        <RulesView hidden={section !== "rules"} />
        <OrdersView hidden={section !== "orders"} />
        <DepartmentsTab hidden={section !== "departments"} />
        <TargetsTab hidden={section !== "targets"} />
        <HealthTab hidden={section !== "health"} />
      </main>

      {withPanel && <RulePanel />}
    </div>
  );
}
