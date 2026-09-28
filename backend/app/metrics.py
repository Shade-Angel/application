"""Prometheus instruments shared by the API, matching worker, and admin router."""

from prometheus_client import Counter, Gauge, Histogram

orders_ingested = Counter("orders_ingested_total", "Orders accepted by the ingest API")
assignments_confirmed = Counter("assignments_confirmed_total", "Confirmed AIS assignments")
assignment_latency = Histogram("assignment_latency_seconds", "Ingest-to-confirmation latency")
assignment_reasons = Counter("assignments_total", "Executor assignments made", ["reason"])
reservation_conflicts = Counter(
    "reservation_conflicts_total", "Reservation retries after database conflicts"
)
stream_pending_metric = Gauge("stream_lag", "Pending Redis stream messages")
outbox_pending_metric = Gauge("outbox_pending", "Undelivered transactional outbox entries")
dead_letter_metric = Gauge("dlq_size", "Outbox dead letter entries")
fairness_metric = Gauge("fairness_max_deviation", "Maximum load deviation within executor pools")
executor_open_weight = Gauge(
    "executor_open_weight", "Current open assigned weight", ["executor_id"]
)
executor_day_weight = Gauge("executor_day_weight", "Current daily assigned weight", ["executor_id"])
