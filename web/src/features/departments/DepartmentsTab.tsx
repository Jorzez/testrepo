import { useCatalog } from "../../state/catalog";
import { archivedClass, ArchivedBadge, Chip, IdBadge } from "../../ui/common";
import { MenuButton } from "../../ui/Menu";
import { useActions } from "../actions";

/* Справочник подразделений. Идентификатор — тот, что кадровая система
   передаёт в запросе проверки (department_id). Какие правила действуют
   только здесь и какие здесь не применяются, задаётся у самого правила. */

export function DepartmentsTab({ hidden }: { hidden: boolean }) {
  const { departments, showArchivedDepartments, reload } = useCatalog();
  const actions = useActions();

  return (
    <section id="tab-departments" className={hidden ? "hidden" : ""}>
      <div className="page-head">
        <div>
          <h1>Подразделения</h1>
          <div className="sub">Идентификатор передаёт кадровая система в запросе проверки. Где какое правило действует — в разделе «Правила».</div>
        </div>
        <button className="btn primary" onClick={actions.addDepartment}>+ Подразделение</button>
      </div>
      <div className="toolbar">
        <label className="check">
          <input type="checkbox" checked={showArchivedDepartments}
            onChange={(e) => void reload({ showArchivedDepartments: e.target.checked })} /> Архив
        </label>
      </div>
      {departments.length ? (
        <div className="card"><table>
          <thead>
            <tr>
              <th style={{ width: "18%" }}>Идентификатор</th><th>Название</th>
              <th style={{ width: "22%" }}>Только здесь действуют</th>
              <th style={{ width: "22%" }}>Здесь не применяются</th>
              <th style={{ width: 70 }} />
            </tr>
          </thead>
          <tbody>
            {departments.map((d) => (
              <tr key={d.nodeId} className={archivedClass(d.status)} data-node={d.nodeId}>
                <td>
                  <span className="mono">{d.departmentId}</span>{" "}
                  <IdBadge value={d.departmentId} name="departmentId" /><ArchivedBadge status={d.status} />
                </td>
                <td>{d.name || <span className="dim">без названия</span>}</td>
                <td>{d.onlyRules.length
                  ? d.onlyRules.map((r) => <Chip key={r}>{r}</Chip>)
                  : <span className="dim">—</span>}</td>
                <td>{d.exceptRules.length
                  ? d.exceptRules.map((r) => (
                    <Chip key={r.ruleId}>{r.ruleId}{r.status === "active" ? "" : " · кандидат"}</Chip>
                  ))
                  : <span className="dim">—</span>}</td>
                <td><div className="actions"><MenuButton items={() => actions.departmentMenu(d)} /></div></td>
              </tr>
            ))}
          </tbody>
        </table></div>
      ) : <div className="empty">Подразделений нет. Пока их нет, все правила действуют для всех.</div>}
    </section>
  );
}
