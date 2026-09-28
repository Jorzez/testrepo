import { API_BASE } from "./api/client";
import { CatalogTab } from "./features/catalog/CatalogTab";
import { CheckTab } from "./features/check/CheckTab";
import { HealthTab } from "./features/health/HealthTab";
import { TargetsTab } from "./features/targets/TargetsTab";
import { useCatalog, type Tab } from "./state/catalog";

const TABS: { id: Tab; label: string }[] = [
  { id: "catalog", label: "Приказы и пункты" },
  { id: "targets", label: "Атрибуты" },
  { id: "check", label: "Проверка цели" },
  { id: "health", label: "Диагностика" },
];

const API_STATE = {
  connecting: { cls: "archived", text: "подключение…" },
  online: { cls: "ok", text: "API на связи" },
  offline: { cls: "warn", text: "API недоступен" },
};

export function App() {
  const { tab, setTab, apiState, health, reload } = useCatalog();
  const pill = API_STATE[apiState];
  // На вкладке — число ошибок, а если их нет, то предупреждений.
  const badge = health?.error || health?.warning || 0;

  return (
    <>
      <header>
        <div className="head-row">
          <div className="brand">Каталог нормативных требований<small>{API_BASE}</small></div>
          <span className={`badge ${pill.cls}`}>{pill.text}</span>
          <button className="btn sm" onClick={() => void reload()}>Обновить</button>
        </div>
        <nav role="tablist">
          {TABS.map((t) => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}>
              {t.label}
              {t.id === "health" && badge > 0 && (
                <span className={`badge count ${health?.error ? "err" : "warn"}`}>{badge}</span>
              )}
            </button>
          ))}
        </nav>
      </header>
      {/* Вкладки не размонтируются: введённая цель и раскрытые узлы сохраняются при переключении. */}
      <main>
        <CatalogTab hidden={tab !== "catalog"} />
        <TargetsTab hidden={tab !== "targets"} />
        <CheckTab hidden={tab !== "check"} />
        <HealthTab hidden={tab !== "health"} />
      </main>
    </>
  );
}
