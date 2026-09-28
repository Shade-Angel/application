from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dsl import compile_condition
from app.metrics import assignment_reasons
from app.models import (
    AssignmentLog,
    CandidateDecision,
    Executor,
    ExecutorDailyUsage,
    Order,
    Outbox,
    Rule,
    StrategySettings,
    StreamEvent,
)


def executor_score(
    executor: Executor,
    alpha: float,
    beta: float,
    gamma: float,
    bonus: float = 0.0,
) -> float:
    capacity = max(float(executor.capacity), 0.001)
    daily_denominator = max(executor.daily_limit or max(executor.day_count, 1), 1)
    return (
        alpha * float(executor.open_weight) / capacity
        + beta * float(executor.day_weight) / daily_denominator / capacity
        - gamma * bonus
    )


def select_candidate(
    candidates: list[Executor],
    preferred_id: int | None,
    score: Callable[[Executor], float],
    eligible_ids: set[int] | None = None,
) -> Executor:
    """Prefer an eligible parent executor; otherwise take the least-loaded eligible executor."""
    if eligible_ids is not None:
        candidates = [
            candidate
            for candidate in candidates
            if candidate.id in eligible_ids or candidate.id == preferred_id
        ]
    preferred = next((executor for executor in candidates if executor.id == preferred_id), None)
    if preferred is not None:
        return preferred
    return min(
        candidates,
        key=lambda executor: (score(executor), executor.last_assigned_at is not None, executor.id),
    )


async def assign(db: AsyncSession, order: Order) -> Executor | None:
    """Lock eligible executors before counters change, preventing concurrent limit overbooking."""
    local_day = datetime.now(ZoneInfo(settings.limit_tz)).date()
    executors = list(
        (
            await db.scalars(
                select(Executor)
                .where(Executor.is_active.is_(True))
                .order_by(Executor.id)
                .with_for_update()
            )
        ).all()
    )
    for executor in executors:
        if executor.day_date != local_day:
            executor.day_date = local_day
            executor.day_count = 0
            executor.day_weight = Decimal(0)
        usage = await db.scalar(
            select(ExecutorDailyUsage)
            .where(
                ExecutorDailyUsage.executor_id == executor.id,
                ExecutorDailyUsage.day_date == local_day,
            )
            .with_for_update()
        )
        if usage is None:
            usage = ExecutorDailyUsage(
                executor_id=executor.id,
                day_date=local_day,
                assigned_count=(executor.day_count if executor.day_date == local_day else 0),
                assigned_weight=(
                    executor.day_weight if executor.day_date == local_day else Decimal(0)
                ),
            )
            db.add(usage)
            await db.flush()
        executor.day_count = usage.assigned_count
        executor.day_weight = usage.assigned_weight
    stored_rules = list(
        (await db.scalars(select(Rule).where(Rule.enabled.is_(True)).order_by(Rule.priority))).all()
    )
    try:
        rules = [
            compile_condition(rule.condition, rule.null_policy)
            for rule in stored_rules
            if rule.kind == "filter"
        ]
        rules.extend(
            compile_condition(rule, str(order.attributes.get("null_policy", "fail")))
            for rule in order.attributes.get("rules", [])
        )
    except ValueError:
        order.assignment_state = "unassignable"
        db.add(
            AssignmentLog(
                order_id=order.id,
                executor_id=None,
                reason="invalid_rule",
                detail="Stored matching condition is invalid; review rule JSON.",
            )
        )
        return None
    base_weight = Decimal(str(order.attributes.get("weight", 1)))
    order_context = {"order": order.attributes, "executor": {}}
    for weight_rule in (rule for rule in stored_rules if rule.kind == "order_weight"):
        if (
            compile_condition(weight_rule.condition, weight_rule.null_policy)(order_context)
            and weight_rule.effect
        ):
            value = Decimal(str(weight_rule.effect.get("value", 1)))
            if weight_rule.effect.get("mode") == "add":
                base_weight += value
            else:
                base_weight *= value
    order.weight = base_weight
    strategy = await db.get(StrategySettings, 1)
    alpha = float(strategy.alpha) if strategy else 1.0
    beta = float(strategy.beta) if strategy else 0.3
    gamma = float(strategy.gamma) if strategy else 1.0

    def effective_capacity(executor: Executor) -> float:
        capacity = float(executor.capacity)
        context = {"order": order.attributes, "executor": executor.attributes}
        for capacity_rule in (rule for rule in stored_rules if rule.kind == "executor_capacity"):
            if (
                compile_condition(capacity_rule.condition, capacity_rule.null_policy)(context)
                and capacity_rule.effect
            ):
                value = float(capacity_rule.effect.get("value", 1))
                capacity = (
                    capacity + value
                    if capacity_rule.effect.get("mode") == "add"
                    else capacity * value
                )
        return max(capacity, 0.001)

    def eligible(executor: Executor) -> bool:
        return all(
            rule({"order": order.attributes, "executor": executor.attributes}) for rule in rules
        )

    rejections: dict[str, str] = {}
    for executor in executors:
        if not eligible(executor):
            rejections[str(executor.id)] = "filter_mismatch"
        elif executor.daily_limit is not None and executor.day_count >= executor.daily_limit:
            rejections[str(executor.id)] = "daily_limit"
        else:
            rejections[str(executor.id)] = "eligible"
    order.attributes = {**order.attributes, "candidate_rejections": rejections}

    eligible_ids = {
        e.id
        for e in executors
        if (e.daily_limit is None or e.day_count < e.daily_limit) and eligible(e)
    }
    candidates = [e for e in executors if e.id in eligible_ids]
    parent_executor_id: int | None = None
    if order.parent_id is not None:
        parent = await db.get(Order, order.parent_id)
        if parent is not None and parent.executor_id is not None:
            preferred = next((e for e in executors if e.id == parent.executor_id), None)
            if preferred is not None and eligible(preferred):
                parent_executor_id = preferred.id
                candidates.insert(0, preferred)
    if not candidates:
        order.assignment_state = "unassignable"
        order.rejection_reason = "no_active_candidate_passed_filters_or_daily_limit"
        db.add_all(
            CandidateDecision(
                order_id=order.id,
                executor_id=executor.id,
                passed=False,
                reason=rejections[str(executor.id)],
                detail={"active": executor.is_active},
            )
            for executor in executors
        )
        assignment_reasons.labels("unassignable").inc()
        db.add(
            AssignmentLog(
                order_id=order.id,
                executor_id=None,
                reason="unassignable",
                detail=str(rejections),
            )
        )
        return None

    def score(executor: Executor) -> float:
        bonus = 0.0
        context = {"order": order.attributes, "executor": executor.attributes}
        for bonus_rule in (rule for rule in stored_rules if rule.kind == "score_bonus"):
            if (
                compile_condition(bonus_rule.condition, bonus_rule.null_policy)(context)
                and bonus_rule.effect
            ):
                bonus += float(bonus_rule.effect.get("value", 0))
        capacity = effective_capacity(executor)
        day_limit = max(executor.daily_limit or max(executor.day_count, 1), 1)
        cumulative_weight = (
            beta * float(executor.day_weight) / day_limit / capacity
            if strategy is not None and strategy.mode == "cumulative_fair"
            else 0.0
        )
        return alpha * float(executor.open_weight) / capacity + cumulative_weight - gamma * bonus

    chosen = select_candidate(candidates, parent_executor_id, score, eligible_ids)
    decisions: list[CandidateDecision] = []
    for executor in executors:
        reason = rejections[str(executor.id)]
        passed = executor.id in eligible_ids or executor.id == parent_executor_id
        if executor.id not in eligible_ids and executor.id == parent_executor_id:
            reason = "parent_affinity_limit_bypassed"
        decisions.append(
            CandidateDecision(
                order_id=order.id,
                executor_id=executor.id,
                passed=passed,
                reason=reason,
                score=Decimal(str(score(executor))) if passed else None,
                detail={"active": executor.is_active, "daily_limit": executor.daily_limit},
            )
        )
    db.add_all(decisions)
    parent_preferred = chosen.id == parent_executor_id
    order.executor_id = chosen.id
    order.assignment_state = "reserved"
    order.rejection_reason = None
    order.holds_slot = True
    order.attributes = {**order.attributes, "assignment_day": local_day.isoformat()}
    order.attempts += 1
    chosen.open_count += 1
    chosen.open_weight += order.weight
    chosen.day_count += 1
    chosen.day_weight += order.weight
    usage = await db.scalar(
        select(ExecutorDailyUsage)
        .where(
            ExecutorDailyUsage.executor_id == chosen.id,
            ExecutorDailyUsage.day_date == local_day,
        )
        .with_for_update()
    )
    if usage is not None:
        usage.assigned_count += 1
        usage.assigned_weight += order.weight
    db.add(
        Outbox(
            order_id=order.id,
            executor_id=chosen.id,
            idempotency_key=f"{order.id}:{order.attempts}",
        )
    )
    daily_limit = str(chosen.daily_limit) if chosen.daily_limit is not None else "unlimited"
    db.add(
        AssignmentLog(
            order_id=order.id,
            executor_id=chosen.id,
            reason="parent" if parent_preferred else "reassign" if order.attempts > 1 else "new",
            detail=(
                f"score={score(chosen):.6f}; open_weight={chosen.open_weight}; "
                f"daily={chosen.day_count}/{daily_limit}"
            ),
        )
    )
    assignment_reasons.labels("parent" if parent_preferred else "new").inc()
    return chosen


async def retry_unassignable(db: AsyncSession) -> int:
    """Requeue unassignable orders after a rule or executor cache change."""
    orders = list(
        (
            await db.scalars(
                select(Order).where(Order.assignment_state == "unassignable").order_by(Order.id)
            )
        ).all()
    )
    db.add_all(StreamEvent(order_id=order.id) for order in orders)
    return len(orders)
