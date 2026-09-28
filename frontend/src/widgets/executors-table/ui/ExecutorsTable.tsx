import type { Executor } from "@/shared/types/types";

export const ExecutorsTable = ({ executors }: { executors: Executor[] }) => (
  <div className="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Исполнитель</th>
          <th>Состояние</th>
          <th>Открыто</th>
          <th>За день</th>
          <th>Лимит</th>
        </tr>
      </thead>
      <tbody>
        {executors.map((e) => (
          <tr key={e.id}>
            <td>{e.name || `Исполнитель ${e.id}`}</td>
            <td>
              <span className={`badge ${e.is_active ? "ok" : "off"}`}>
                {e.is_active ? "Активен" : "Неактивен"}
              </span>
            </td>
            <td>
              {e.open_count} ({e.open_weight})
            </td>
            <td>{e.day_count}</td>
            <td>{e.daily_limit ?? "∞"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);
