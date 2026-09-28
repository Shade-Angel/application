import { useState } from "react";
import { api } from "@/shared/api/base";
import type { OrderExplain } from "@/shared/types/types";

export const useOrderExplain = () => {
  const [selected, setSelected] = useState<OrderExplain | null>(null);
  const explain = async (orderId: number) => {
    try {
      setSelected(await api<OrderExplain>(`/api/orders/${orderId}/explain`));
    } catch {
      setSelected(null);
    }
  };
  return { selected, explain };
};
