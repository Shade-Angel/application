import { useCallback, useEffect, useState } from "react";
import { PanelTitle } from "@/shared/ui/PanelTitle";
import { api } from "@/shared/api/base";
import { useAppData } from "@/shared/context/AppDataContext";

type Dead = {
  outbox: Array<Record<string, unknown>>;
  stream: Array<Record<string, unknown>>;
};

export const AuditDlq = () => {
  const { setNotice } = useAppData();
  const [events, setEvents] = useState<Array<Record<string, unknown>>>([]);
  const [dead, setDead] = useState<Dead>({ outbox: [], stream: [] });

  const refresh = useCallback(async () => {
    try {
      const [audit, queue] = await Promise.all([
        api<Array<Record<string, unknown>>>("/api/audit"),
        api<Dead>("/api/dlq"),
      ]);
      setEvents(audit);
      setDead(queue);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Не удалось загрузить аудит");
    }
  }, [setNotice]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const retry = async (path: string) => {
    try {
      await api(path, { method: "POST" });
      await refresh();
      setNotice("Событие отправлено на повторную обработку");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Не удалось повторить событие");
    }
  };

  return (
    <div className="grid">
      <section className="panel">
        <PanelTitle
          title="Журнал назначений"
          subtitle={`${events.length} событий`}
        />
        {events.map((event, index) => (
          <div className="rule-row" key={index}>
            <div>
              <strong>Заявка #{String(event.order_id)}</strong>
              <pre>
                {String(event.reason)} · исполнитель{" "}
                {String(event.executor_id ?? "—")} · {String(event.created_at)}
              </pre>
            </div>
          </div>
        ))}
      </section>
      <section className="panel">
        <PanelTitle
          title="Dead letter queue"
          subtitle={`${dead.outbox.length + dead.stream.length} событий`}
        />
        {dead.outbox.map((item) => (
          <div className="rule-row" key={String(item.id)}>
            <div>
              <strong>
                Outbox #{String(item.id)} · заявка {String(item.order_id)}
              </strong>
              <pre>Попыток: {String(item.attempts)}</pre>
            </div>
            <button onClick={() => void retry(`/api/dlq/outbox/${String(item.id)}/retry`)}>
              Повторить
            </button>
          </div>
        ))}
        {dead.stream.map((item) => (
          <div className="rule-row" key={String(item.id)}>
            <div>
              <strong>Stream #{String(item.id)} · заявка {String(item.order_id ?? "—")}</strong>
              <pre>{String(item.error ?? item.reason ?? "Сообщение из очереди ошибок")}</pre>
            </div>
            <button onClick={() => void retry(`/api/dlq/stream/${encodeURIComponent(String(item.id))}/retry`)}>
              Повторить
            </button>
          </div>
        ))}
      </section>
    </div>
  );
};
