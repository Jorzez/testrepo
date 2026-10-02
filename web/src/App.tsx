import type { ReactNode } from "react";

import logo from "./assets/logo.png";
import { CheckView } from "./features/check/CheckView";
import { DepartmentsTab } from "./features/departments/DepartmentsTab";
import { HealthTab } from "./features/health/HealthTab";
import { OrdersView } from "./features/orders/OrdersView";
import { RulePanel } from "./features/rules/RulePanel";
import { RulesView } from "./features/rules/RulesView";
import { TargetsTab } from "./features/targets/TargetsTab";
import { UsersTab } from "./features/users/UsersTab";
import { ROLE_LABEL, useAuth } from "./state/auth";
import { useCatalog, type Section } from "./state/catalog";

const icon = (path: ReactNode) => (
  <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
    aria-hidden="true">{path}</svg>
);

const SECTIONS: { id: Section; label: string; icon: ReactNode; adminOnly?: boolean }[] = [
  { id: "check", label: "Проверка цели", icon: icon(<path d="M4 10l4 4 8-9" />) },
  { id: "rules", label: "Правила", icon: icon(<path d="M3 3h14v14H3zM3 8h14M3 13h14M8 3v14M13 3v14" />) },
  { id: "orders", label: "Приказы", icon: icon(<path d="M5 2h8l3 3v13H5zM8 8h6M8 12h6" />) },
  { id: "departments", label: "Подразделения", icon: icon(<><circle cx="10" cy="7" r="3" /><path d="M4 17c0-3 3-5 6-5s6 2 6 5" /></>) },
  { id: "targets", label: "Атрибуты", icon: icon(<path d="M3 5h9l5 5-5 5H3zM7 10h.01" />) },
  { id: "health", label: "Замечания", icon: icon(<path d="M10 3l8 14H2zM10 8v4M10 14.5v.5" />) },
  { id: "users", label: "Пользователи", adminOnly: true,
    icon: icon(<><circle cx="7.5" cy="7" r="2.6" /><path d="M2.5 16c0-2.6 2.2-4.4 5-4.4s5 1.8 5 4.4M13.5 4.6a2.6 2.6 0 010 4.8M15 11.8c1.6.6 2.6 2 2.6 4.2" /></>) },
];

const API_STATE = {
  connecting: { cls: "archived", text: "подключение…" },
  online: { cls: "ok", text: "API на связи" },
  offline: { cls: "warn", text: "API недоступен" },
};

export function App() {
  const { section, setSection, apiState, health, reload, panelRule, wizard } = useCatalog();
  const { user, isAdmin, logout } = useAuth();
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
          {SECTIONS.filter((s) => isAdmin || !s.adminOnly).map((s) => (
            <button key={s.id} role="tab" className="nav-item" aria-selected={section === s.id} onClick={() => setSection(s.id)}>
              {s.icon}{s.label}
              {s.id === "health" && badge > 0 && <span className={`n ${health?.error ? "err" : "warn"}`}>{badge}</span>}
            </button>
          ))}
        </nav>
        <div className="spacer" />
        <div className="side-foot">
          <div className="who">
            <div className="mid">{user.displayName || user.login}</div>
            <div className="small dim">{user.displayName ? `${user.login} · ` : ""}{ROLE_LABEL[user.role]}</div>
          </div>
          <span className={`badge ${pill.cls}`}><span className="dot" />{pill.text}</span>
          <div className="row" style={{ gap: 6 }}>
            <button className="btn sm" onClick={() => void reload()}>Обновить</button>
            <button className="btn sm ghost" onClick={() => void logout()}>Выйти</button>
          </div>
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
        {isAdmin && <UsersTab hidden={section !== "users"} />}
      </main>

      {withPanel && <RulePanel />}
    </div>
  );
}
