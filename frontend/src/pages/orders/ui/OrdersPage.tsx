import { useAppData } from "@/shared/context/AppDataContext";
import { PanelTitle } from "@/shared/ui/PanelTitle";
import { OrdersTable } from "@/widgets/orders-table/ui/OrdersTable";

export const OrdersPage = () => {
  const { orders } = useAppData();
  return (
    <section className="panel">
      <PanelTitle title="Заявки" subtitle={`${orders.length} записей`} />
      <OrdersTable orders={orders.slice().reverse()} />
    </section>
  );
};
