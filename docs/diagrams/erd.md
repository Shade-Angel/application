# ERD схемы данных

В PostgreSQL находятся две логические схемы. `balancer` — рабочая модель распределителя; `ais` — модель эмулятора внешней АИС. Линии внутри каждой схемы отражают объявленные внешние ключи и уникальные связи ORM. Связи между заявкой АИС и заявкой балансировщика сопоставляются по исходному `id` интеграционным webhook и физическими FK между схемами не являются.

```mermaid
erDiagram
  EXECUTORS ||--o{ ORDERS : "назначен исполнителю"
  ORDERS ||--o{ ORDERS : "parent_id логическая связь"
  EXECUTORS ||--o{ EXECUTOR_DAILY_USAGE : "учёт за день"
  ORDERS ||--o{ ASSIGNMENT_LOG : "история решений"
  ORDERS ||--o{ CANDIDATE_DECISIONS : "оценка кандидатов"
  ORDERS ||--o{ OUTBOX : "доставка назначения"
  ORDERS ||--o{ STREAM_EVENTS : "очередь распределения"
  DICTIONARIES ||--o{ DICTIONARY_ITEMS : "допустимые значения"
  DICTIONARIES o|--o{ PARAMETER_DEFINITIONS : "словарный параметр"
  AIS_USERS ||--o| AIS_USER_SETTINGS : "настройки"
  AIS_USERS ||--o{ AIS_ORDERS : "user_id источник"
  AIS_ORDERS ||--o{ AIS_ASSIGNMENTS : "внешнее назначение"

  EXECUTORS {
    bigint id PK
    string name
    boolean is_active
    jsonb attributes
    numeric capacity
    int daily_limit
    int open_count
    numeric open_weight
    date day_date
    int day_count
    numeric day_weight
    datetime source_updated_at
  }
  ORDERS {
    bigint id PK
    bigint parent_id
    string status
    jsonb attributes
    numeric weight
    bigint executor_id FK
    string assignment_state
    boolean holds_slot
    int attempts
    datetime received_at
    datetime assigned_at
    datetime confirmed_at
  }
  EXECUTOR_DAILY_USAGE {
    bigint id PK
    bigint executor_id
    date day_date
    int assigned_count
    numeric assigned_weight
  }
  ASSIGNMENT_LOG {
    bigint id PK
    bigint order_id
    bigint executor_id
    string reason
    text detail
    datetime created_at
  }
  CANDIDATE_DECISIONS {
    bigint id PK
    bigint order_id
    bigint executor_id
    boolean passed
    string reason
    numeric score
    jsonb detail
  }
  OUTBOX {
    bigint id PK
    bigint order_id
    bigint executor_id
    string idempotency_key UK
    string status
    int attempts
    datetime retry_at
  }
  STREAM_EVENTS {
    bigint id PK
    bigint order_id
    datetime published_at
    datetime created_at
  }
  PROCESSED_EVENTS {
    string event_id PK
    datetime received_at
  }
  RULES {
    int id PK
    string name
    string kind
    jsonb condition
    jsonb effect
    int priority
    boolean enabled
    string null_policy
  }
  PARAMETER_DEFINITIONS {
    int id PK
    string entity
    string key UK
    string data_type
    int dictionary_id FK
    boolean is_system
  }
  DICTIONARIES {
    int id PK
    string code UK
    string label
  }
  DICTIONARY_ITEMS {
    int id PK
    int dictionary_id FK
    string value
    string label
  }
  STRATEGY_SETTINGS {
    int id PK
    string mode
    numeric alpha
    numeric beta
    numeric gamma
  }
  AIS_USERS {
    bigint id PK
    string first_name
    string last_name
    string middle_name
    string status
    jsonb settings_json
  }
  AIS_USER_SETTINGS {
    bigint id PK
    bigint user_id FK_UK
    bigint min_accept_sum
    bigint max_accept_sum
    bigint min_reject_sum
    bigint max_reject_sum
    string client_msp
    string executor_msp
    string order_type
    string subject
    boolean vip
    smallint max_daily_limit
    jsonb extra_settings
  }
  AIS_ORDERS {
    bigint id PK
    bigint parent_id
    bigint user_id
    bigint amount
    numeric weight
    string client_msp
    string executor_msp
    string order_type
    string subject
    boolean vip
    string status
    bigint executor_id
    jsonb attributes_json
  }
  AIS_ASSIGNMENTS {
    bigint id
    bigint order_id PK
    bigint executor_id
    string idempotency_key PK
  }
```

`ExecutorDailyUsage` гарантирует уникальность пары `(executor_id, day_date)`. `AIS_ASSIGNMENTS` имеет составной первичный ключ `(order_id, idempotency_key)`. Часть связей журналов и очереди намеренно логическая и не объявлена как FK в базе. В отдельной агрегатной таблице метрики не хранятся: сводные значения вычисляются из событий и текущих счётчиков.
