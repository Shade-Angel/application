import { useAppData } from "@/shared/context/AppDataContext";
import { Kpi } from "@/shared/ui/Kpi";
import { CreateOrderButton } from "@/features/create-order/ui/CreateOrderButton";
import { OrdersTable } from "@/widgets/orders-table/ui/OrdersTable";
import {
  TimelineChart,
  LoadChart,
} from "@/widgets/dashboard-charts/ui/DashboardCharts";

export const DashboardPage = () => {
  const { analytics, executors, orders } = useAppData();
  const assigned = analytics.assigned;
  const waiting = analytics.pending + analytics.unassignable;
  const active = analytics.active_executors;

  return (
    <>
      <section className="cards">
        <Kpi
          title="Заявок получено"
          value={analytics.rps_in_per_minute ?? analytics.orders}
          note="за последнюю минуту"
        />
        <Kpi
          title="Назначено"
          value={analytics.rps_assigned_per_minute ?? assigned}
          note="за последнюю минуту"
        />
        <Kpi
          title="Ожидают назначения"
          value={waiting}
          note="в очереди или без кандидата"
        />
        <Kpi
          title="Активные исполнители"
          value={`${active} / ${executors.length}`}
          note="актуальный список"
        />
        <Kpi
          title="p50 / p95"
          value={`${analytics.p50_latency_seconds.toFixed(2)} / ${analytics.p95_latency_seconds.toFixed(2)} с`}
          note="до подтверждения AIS"
        />
        <Kpi
          title="Stream pending"
          value={analytics.queue_lag}
          note={`в потоке ${analytics.stream_length}`}
        />
        <Kpi
          title="Outbox / DLQ"
          value={`${analytics.outbox_pending} / ${analytics.dlq}`}
          note="доставка AIS"
        />
        <Kpi
          title="Fairness max"
          value={`${(analytics.fairness_max_deviation * 100).toFixed(1)}%`}
          note="внутри допуск-пулов"
        />
      </section>
      <TimelineChart />
      <LoadChart />
      <section className="panel">
        <div className="panel-title">
          <div>
            <small>EXECUTOR BALANCER</small>
            <h2>Последние заявки</h2>
          </div>
          <CreateOrderButton />
        </div>
        <OrdersTable orders={orders.slice(-15).reverse()} />
      </section>
    </>
  );
};
