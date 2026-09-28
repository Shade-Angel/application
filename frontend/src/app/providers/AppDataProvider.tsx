import { useState, useEffect, useCallback, type ReactNode } from "react";
import { api } from "@/shared/api/base";
import { AppDataContext, type AppData } from "../../shared/context/AppDataContext";
import type {
  Executor,
  Order,
  Rule,
  Parameter,
  Strategy,
  Analytics,
  Dictionary,
} from "@/shared/types/types";

export const AppDataProvider = ({ children }: { children: ReactNode }) => {
  const [executors, setExecutors] = useState<Executor[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [parameters, setParameters] = useState<Parameter[]>([]);
  const [dictionaries, setDictionaries] = useState<Dictionary[]>([]);
  const [strategy, setStrategy] = useState<Strategy>({
    mode: "open_load",
    alpha: 1,
    beta: 0.3,
    gamma: 1,
  });
  const [analytics, setAnalytics] = useState<Analytics>({
    orders: 0,
    assigned: 0,
    pending: 0,
    unassignable: 0,
    active_executors: 0,
    p50_latency_seconds: 0,
    p95_latency_seconds: 0,
    queue_lag: 0,
    stream_length: 0,
    outbox_pending: 0,
    dlq: 0,
    fairness_max_deviation: 0,
  });
  const [online, setOnline] = useState(false);
  const [notice, setNoticeState] = useState("");

  const setNotice = useCallback((text: string) => {
    setNoticeState(text);
    window.setTimeout(() => setNoticeState(""), 3500);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [e, o, r, p, s, d, a] = await Promise.all([
        api<Executor[]>("/api/executors"),
        api<Order[]>("/api/orders"),
        api<Rule[]>("/api/rules"),
        api<Parameter[]>("/api/parameters"),
        api<Strategy>("/api/strategy"),
        api<Dictionary[]>("/api/dictionaries"),
        api<Analytics>("/api/analytics/summary"),
      ]);
      setExecutors(e);
      setOrders(o);
      setRules(r);
      setParameters(p);
      setStrategy(s);
      setDictionaries(d);
      setAnalytics(a);
      setOnline(true);
    } catch {
      setOnline(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void refresh();
    });
    const timer = window.setInterval(() => {
      void refresh();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${scheme}://${window.location.host}/ws/live`);
    socket.onopen = () => setOnline(true);
    socket.onclose = () => setOnline(false);
    socket.onmessage = (event) => {
      const data = JSON.parse(event.data) as {
        per_executor?: Executor[];
        last_events?: Order[];
      };
      if (data.per_executor) setExecutors(data.per_executor);
      if (data.last_events)
        setOrders((current) => {
          const byId = new Map(current.map((order) => [order.id, order]));
          data.last_events?.forEach((order) => byId.set(order.id, order));
          return [...byId.values()].slice(-500);
        });
    };
    return () => socket.close();
  }, []);

  const value: AppData = {
    executors,
    orders,
    rules,
    parameters,
    dictionaries,
    strategy,
    analytics,
    online,
    notice,
    refresh,
    setNotice,
  };

  return (
    <AppDataContext.Provider value={value}>{children}</AppDataContext.Provider>
  );
};
