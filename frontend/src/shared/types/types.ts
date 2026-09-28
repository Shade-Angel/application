export type Executor = {
  id: number;
  name: string;
  is_active: boolean;
  open_count: number;
  open_weight: number;
  daily_limit: number | null;
  day_count: number;
};
export type Order = {
  id: number;
  status: string;
  assignment_state: string;
  executor_id: number | null;
  attributes?: Record<string, unknown>;
  received_at?: string;
};
export type Rule = {
  id: number;
  name: string;
  kind: string;
  condition: Record<string, unknown>;
  priority: number;
  enabled: boolean;
};
export type OrderExplain = {
  rejection_reason: string | null;
  candidates: Array<{
    executor_id: number;
    passed: boolean;
    reason: string;
    score: number | null;
  }>;
  history: Array<{
    executor_id: number | null;
    reason: string;
    detail: string;
    at: string;
  }>;
};
export type Parameter = {
  id: number;
  entity: string;
  key: string;
  label: string;
  data_type: string;
  dictionary_id?: number | null;
  is_system: boolean;
};
export type Strategy = {
  mode: string;
  alpha: number;
  beta: number;
  gamma: number;
};
export type Analytics = {
  orders: number;
  assigned: number;
  pending: number;
  unassignable: number;
  active_executors: number;
  rps_in_per_minute?: number;
  rps_assigned_per_minute?: number;
  p50_latency_seconds: number;
  p95_latency_seconds: number;
  queue_lag: number;
  stream_length: number;
  outbox_pending: number;
  dlq: number;
  fairness_max_deviation: number;
  timeline_15m?: Array<{
    bucket: string;
    rps_in: number;
    rps_assigned: number;
  }>;
};
export type Dictionary = {
  id: number;
  code: string;
  label: string;
  items: Array<{ value: string; label: string }>;
};
export type Page =
  | "Обзор"
  | "Заявки"
  | "Исполнители"
  | "Правила"
  | "Параметры"
  | "Стратегия"
  | "Симулятор"
  | "Audit / DLQ";
