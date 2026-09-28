-- Run against PostgreSQL after a load test. Every query must return zero rows.
-- An open slot must be reflected exactly once in the executor counters.
SELECT e.id, e.open_count, COUNT(o.id) AS actual_open
FROM balancer.executors e
LEFT JOIN balancer.orders o ON o.executor_id = e.id AND o.holds_slot IS TRUE
GROUP BY e.id, e.open_count
HAVING e.open_count <> COUNT(o.id);

-- No active/open reservation may point at a deactivated executor.
SELECT o.id, o.executor_id
FROM balancer.orders o
JOIN balancer.executors e ON e.id = o.executor_id
WHERE o.holds_slot IS TRUE AND e.is_active IS FALSE;

-- Daily caps may be exceeded only by an eligible parent-linked reservation.
SELECT e.id, e.day_count, e.daily_limit
FROM balancer.executors e
WHERE e.daily_limit IS NOT NULL AND e.day_count > e.daily_limit
  AND NOT EXISTS (
    SELECT 1 FROM balancer.orders o
    JOIN balancer.orders parent ON parent.id = o.parent_id
    WHERE o.executor_id = e.id AND parent.executor_id = e.id
  );

-- Every current reservation has one executor and no self-parent relationship.
SELECT o.id FROM balancer.orders o
WHERE (o.holds_slot IS TRUE AND o.executor_id IS NULL)
   OR (o.parent_id = o.id);
