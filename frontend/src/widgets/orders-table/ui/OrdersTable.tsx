import { useOrderExplain } from "@/features/order-explain/model/useOrderExplain";
import { ExplainPanel } from "@/features/order-explain/ui/ExplainPanel";
import type { Order } from "@/shared/types/types";

export const OrdersTable = ({ orders }: { orders: Order[] }) => {
  const { selected, explain } = useOrderExplain();
  return (
    <>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Статус</th>
              <th>Назначение</th>
              <th>Исполнитель</th>
              <th>Тип заявки</th>
              <th>Разбор</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => (
              <tr key={order.id}>
                <td>#{order.id}</td>
                <td>{order.status}</td>
                <td>
                  <span className="badge">{order.assignment_state}</span>
                </td>
                <td>{order.executor_id ?? "—"}</td>
                <td>{String(order.attributes?.order_type ?? "—")}</td>
                <td>
                  <button onClick={() => void explain(order.id)}>
                    Explain
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!orders.length && <p className="empty">Записей пока нет.</p>}
      </div>
      {selected && <ExplainPanel selected={selected} />}
    </>
  );
};
