# Принятые решения и соответствие кейсу

## ADR-001. Модульный монолит

API, Redis consumer, transactional stream publisher и outbox dispatcher — отдельные процессы одного Python-пакета. PostgreSQL — источник истины, Redis Streams — брокер событий. При заданной нагрузке Kafka добавила бы эксплуатационную сложность без нужного выигрыша; consumer groups, ACK, `XAUTOCLAIM` и DLQ покрывают требуемую доставку.

## Маппинг полей организаторов

Поля из `Кейс_хакатон_2026.docx` считаются авторитетными. Фиксированные поля также копируются в JSONB attributes, чтобы DSL мог работать по унифицированному пути.

| Сущность | Поля кейса | Балансировщик / AIS emulator |
|---|---|---|
| `users` | `id`, `first_name`, `last_name`, `middle_name`, `status` (`active/inactive`) | AIS schema `ais.ais_users`; `balancer.executors.id`, `name`, `is_active`; имя и статус сохранены также в attributes |
| `user_settings` | `user_id`, `min_accept_sum`, `max_accept_sum`, `min_reject_sum`, `max_reject_sum`, `client_msp`, `executor_msp`, `order_type`, `subject`, `vip`, `max_daily_limit` | AIS `ais_user_settings` stores fixed columns plus JSONB `extra_settings`; AIS `ais_users.settings_json` is the serialized integration snapshot. The full object is sent to `balancer.executors.attributes`; `max_daily_limit` is also mapped to `daily_limit`. |
| `order` | `id`, `parent_id`, `user_id`, `sum`, `client_msp`, `executor_msp`, `order_type`, `subject`, `vip`, `text`, `status` | AIS `ais_orders`; `balancer.orders.parent_id/status/executor_id`; остальные поля — attributes JSONB; `user_id` не означает назначенного исполнителя |

В тексте SQL организаторов связь настроек указывает `users(user_id)`, хотя ключ таблицы `users` объявлен как `id`; эмулятор использует `users.id` как PK. Предположительные поля `amount`, `type`, `is_active`, `daily_limit`, `qualification` не подменяют исходную схему. `qualification` и `max_daily_limit` используются только как демо-дополнения для capacity и лимита.

## Настройки бизнес-правил

- `REVIEW_STATUS=await`; открытые статусы `processed,await`; закрывающие `accept,reject`.
- Вторичная заявка — заявка с `parent_id`. По умолчанию проверка при `await` выполняется только для таких заявок.
- `REASSIGN_ON_DEACTIVATE=false` по умолчанию. При `true` открытые заявки деактивированного пользователя снимаются с его счётчиков и отправляются на повторный подбор.
- Назначение родительского исполнителя проверяет активность и фильтры, но пропускает проверку суточного лимита; назначение увеличивает дневную статистику.
- Нераспределимая заявка переходит в `unassignable`. При изменении пользователя или фильтрующего правила она ставится в stream повторно.
- Лимитный день вычисляется по `LIMIT_TZ` (по умолчанию `Europe/Moscow`); счётчики сбрасываются при первом подборе в новом локальном дне.

## Границы реализации и проверки

- Один initial Alembic migration создаёт таблицы из ORM metadata. Новые изменения схемы должны добавляться отдельными ревизиями.
- Правила, фильтры, вес заявки, capacity и бонусы подключены к matching. Исполнительские данные берутся из PostgreSQL под блокировкой; отдельный in-memory executor cache/pub-sub не используется, чтобы решение о лимитах всегда опиралось на транзакционные актуальные значения. Компиляция DSL-кода кэшируется по неизменяемому JSON-значению условия.
- В UI реализованы дашборд, заявки, исполнители, React Query Builder, справочники, параметры, стратегия, dry-run, симулятор и Audit/DLQ; текущие пределы UI зафиксированы в README и API-документации.
- Функциональный Docker smoke-прогон проверяет старт и интеграционный маршрут заявки; текущие результаты и acceptance-план находятся в `LOAD_REPORT.md`.
- Целевое fairness отклонение ±1–2% не утверждается без воспроизводимого профиля на чистом наборе. Для него подготовлен отдельный Docker Compose Locust profile `load`.
- Метрики выгружаются через JSON API и XLSX. Отдельная persistent aggregate/materialized таблица, указанная как дополнительный плюс, не реализована.
- Подробное объяснение проблем и альтернативных подходов находится в `PROBLEMS_AND_ALTERNATIVES.md`.
