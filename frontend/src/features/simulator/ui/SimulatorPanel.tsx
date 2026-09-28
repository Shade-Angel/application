import { useEffect, useState } from "react";
import { PanelTitle } from "@/shared/ui/PanelTitle";
import { useAppData } from "@/shared/context/AppDataContext";
import { api } from "@/shared/api/base";

export const SimulatorPanel = () => {
  const { setNotice } = useAppData();
  const [status, setStatus] = useState<{
    running: string[];
    orders: number;
    status_changes: number;
    chaos_changes: number;
  }>({ running: [], orders: 0, status_changes: 0, chaos_changes: 0 });
  const [sim, setSim] = useState({
    rate_per_hour: 4000,
    threads: 4,
    parent_ratio: 0.1,
  });

  useEffect(() => {
    let active = true;
    const updateStatus = async () => {
      try {
        const next = await api<typeof status>("/sim/status");
        if (active) setStatus(next);
      } catch {
        if (active) setNotice("Не удалось получить состояние симулятора");
      }
    };
    void updateStatus();
    const timer = window.setInterval(() => void updateStatus(), 2000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [setNotice]);

  const simulator = async (path: string, body?: unknown) => {
    try {
      await api(`/sim${path}`, {
        method: "POST",
        body: body === undefined ? "{}" : JSON.stringify(body),
      });
      const next = await api<typeof status>("/sim/status");
      setStatus(next);
      setNotice(path === "/stop" ? "Симулятор остановлен" : "Симулятор запущен");
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "Симулятор недоступен",
      );
    }
  };

  const isRunning = (name: string) => status.running.includes(name);

  return (
    <div className="grid">
      <section className="panel simulator-status" aria-live="polite">
        <PanelTitle
          title="Состояние симулятора"
          subtitle={status.running.length ? `Работает: ${status.running.join(", ")}` : "Остановлен"}
        />
        <div className="cards simulator-counters">
          <article><strong>{status.orders}</strong><span>создано заявок</span></article>
          <article><strong>{status.status_changes}</strong><span>смен статуса</span></article>
          <article><strong>{status.chaos_changes}</strong><span>изменений исполнителей</span></article>
        </div>
      </section>
      <section className="panel">
        <PanelTitle
          title="Генерация заявок"
          subtitle="Можно задать нагрузку и количество параллельных потоков"
        />
        <label>
          Заявок в час
          <input
            type="number"
            value={sim.rate_per_hour}
            onChange={(e) =>
              setSim({ ...sim, rate_per_hour: Number(e.target.value) })
            }
          />
        </label>
        <label>
          Потоки
          <input
            type="number"
            min="1"
            max="64"
            value={sim.threads}
            onChange={(e) =>
              setSim({ ...sim, threads: Number(e.target.value) })
            }
          />
        </label>
        <label>
          Доля дочерних заявок
          <input
            type="number"
            min="0"
            max="1"
            step="0.05"
            value={sim.parent_ratio}
            onChange={(e) =>
              setSim({ ...sim, parent_ratio: Number(e.target.value) })
            }
          />
        </label>
        <button
          className="primary"
          disabled={isRunning("orders")}
          onClick={() =>
            void simulator("/orders/start", {
              ...sim,
              burst: { rps: 50, duration_s: 60, every_s: 300 },
            })
          }
        >
          Запустить заявки
        </button>
      </section>
      <section className="panel">
        <PanelTitle
          title="Изменение статусов и исполнителей"
          subtitle="Освобождение слотов и проверка повторного распределения"
        />
        <button
          disabled={isRunning("statuses")}
          onClick={() =>
            void simulator("/statuses/start", {
              threads: 4,
              close_after_s: [10, 45],
              review_ratio: 0.25,
            })
          }
        >
          Запустить статусы
        </button>
        <button
          disabled={isRunning("chaos")}
          onClick={() =>
            void simulator("/executors/chaos", {
              deactivate_ratio: 0.15,
              every_s: 10,
            })
          }
        >
          Запустить chaos исполнителей
        </button>
        <button className="danger" disabled={status.running.length === 0} onClick={() => void simulator("/stop")}>
          Остановить симулятор
        </button>
      </section>
    </div>
  );
};
