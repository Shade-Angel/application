# API

OpenAPI: `http://localhost:8000/docs`, emulator: `http://localhost:8001/docs`.

## Balancer

- `GET /health`, `GET /ready`, `GET /metrics`, `WS /ws/live`
- `POST /ingest/executors`, `POST /ingest/orders`, `POST /ingest/assignment-confirmed`. Webhooks require `X-Webhook-Secret`; event ingest accepts `X-Event-Id` for idempotency.
- Administrative `/api/*` routes require `X-API-Key`, configured by `API_KEY` (demo default: `local-demo-key`).
- `GET /api/parameters`, `POST /api/parameters`, `PUT/DELETE /api/parameters/{id}`
- `GET/POST /api/rules`, `PUT/DELETE /api/rules/{id}`, `PATCH /api/rules/{id}/toggle`, `POST /api/rules/validate`, `POST /api/rules/dry-run`
- `GET/POST /api/dictionaries`, `PUT/DELETE /api/dictionaries/{id}`, `POST /api/dictionaries/{id}/items`, `PUT/DELETE /api/dictionaries/{id}/items/{item_id}`
- `GET/PUT /api/strategy`
- `GET /api/orders?state=&executor_id=&from=&to=`, `GET /api/orders/{id}`, `GET /api/orders/{id}/explain`
- `GET /api/executors?active=&q=`, `GET /api/executors/{id}`
- `GET /api/analytics/summary`, `/analytics/timeline`, `/analytics/fairness?window=1h|today`, `/analytics/export.xlsx`, `/analytics/export.json`
- `GET /api/dashboard/timeline` returns 15 minutes of `bucket`, `rps_in`, `rps_assigned` values for the live dashboard.
- `GET /api/audit`, `GET /api/dlq`, `POST /api/dlq/outbox/{id}/retry`, `POST /api/dlq/stream/{stream_id}/retry`

## AIS emulator

- CRUD: users `/api/users` and `/api/users/{id}`; separate user settings `/api/user-settings` and `/api/user-settings/{user_id}`; orders `/api/orders`, `/api/orders/{id}`, and `/api/orders/{id}/status`.
- `POST /api/assignments` records an idempotent assignment and confirms it after 2–10 seconds.
- Simulation: `POST /sim/orders/start`, `/sim/statuses/start`, `/sim/executors/chaos`, `/sim/stop`; `GET /sim/status`.

## Rules DSL

Leaf: `{"field":"executor.languages","op":"contains","value":{"field":"order.language"}}`. The equivalent organizer form `{"left":{"ref":"executor.languages"},"op":"contains","right":{"ref":"order.language"}}` is accepted. Literals can be strings, numbers, booleans, arrays and null. Operators: scalar comparisons (`eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `between`, `in`, `not_in`), null checks (`is_null`, `not_null`, `exists`), strings (`starts_with`, `ends_with`, `contains_substr`, `regex`), arrays (`contains`, `contains_any`, `contains_all`, `intersects`, `is_empty`), booleans (`implies`) and dates (`within_last`, ISO-8601 duration). Groups: `all` / `any` or nested `rules` with `combinator: and|or` and `not`. Field references are validated against the parameter catalog when saving. `null_policy` is `pass` or `fail`; compiled predicates are cached by condition value.
