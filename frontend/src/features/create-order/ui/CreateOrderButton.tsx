import { useState } from "react";
import { useAppData } from "@/shared/context/AppDataContext";
import { api } from "@/shared/api/base";

export const CreateOrderButton = () => {
  const { refresh, setNotice } = useAppData();
  const [sending, setSending] = useState(false);

  const createSampleOrder = async () => {
    if (sending) return;
    const id = Date.now();
    setSending(true);
    try {
      await api("/ais/api/orders", {
        method: "POST",
        body: JSON.stringify({
          id,
          amount: 120000,
          client_msp: "yes",
          executor_msp: "yes",
          order_type: "ORDER_1",
          subject: "subject-a",
          vip: false,
          text: "Демо заявка из интерфейса",
          status: "processed",
          attributes: { language: "ru" },
        }),
      });
      await refresh();
      setNotice(`Заявка #${id} отправлена в АИС`);
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "Не удалось создать заявку",
      );
    } finally {
      setSending(false);
    }
  };

  return (
    <button className="primary" disabled={sending} onClick={() => void createSampleOrder()}>
      {sending ? "Отправляем заявку…" : "Создать демо-заявку"}
    </button>
  );
};
