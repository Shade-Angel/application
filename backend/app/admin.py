"""Management APIs for dynamic parameters, dictionaries, rules, strategy, and analytics."""

import asyncio
import io
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import Session, session
from app.dsl import compile_condition
from app.matching import retry_unassignable
from app.metrics import (
    dead_letter_metric,
    executor_day_weight,
    executor_open_weight,
    fairness_metric,
    outbox_pending_metric,
    stream_pending_metric,
)
from app.models import (
    AssignmentLog,
    CandidateDecision,
    Dictionary,
    DictionaryItem,
    Executor,
    ExecutorDailyUsage,
    Order,
    Outbox,
    ParameterDefinition,
    Rule,
    StrategySettings,
)


async def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(401, "invalid API key")


router = APIRouter(prefix="/api", dependencies=[Depends(verify_api_key)])


class ParameterIn(BaseModel):
    entity: str
    key: str
    label: str
    data_type: str
    dictionary_id: int | None = None
    is_system: bool = False


class RuleIn(BaseModel):
    name: str
    kind: str
    condition: dict[str, Any]
    effect: dict[str, Any] | None = None
    priority: int = 100
    enabled: bool = True
    null_policy: str = "fail"


class DictionaryIn(BaseModel):
    code: str
    label: str


class ItemIn(BaseModel):
    value: str
    label: str


class StrategyIn(BaseModel):
    mode: str = "open_load"
    alpha: float = Field(default=1, ge=0, le=10)
    beta: float = Field(default=0.3, ge=0, le=10)
    gamma: float = Field(default=1, ge=0, le=10)


class TimelinePoint(BaseModel):
    bucket: datetime
    group: str
    count: int


class ExecutorSummary(BaseModel):
    id: int
    name: str
    is_active: bool
    open_count: int
    open_weight: float
    capacity: float
    daily_limit: int | None
    day_count: int
    day_weight: float


class TimelineRatePoint(BaseModel):
    bucket: datetime
    rps_in: float
    rps_assigned: float


class AnalyticsSummary(BaseModel):
    orders: int
    assigned: int
    pending: int
    unassignable: int
    active_executors: int
    rps_in: float
    rps_assigned: float
    rps_in_per_minute: int
    rps_assigned_per_minute: int
    p50_latency_seconds: float
    p95_latency_seconds: float
    queue_lag: int
    stream_length: int
    outbox_pending: int
    dlq: int
    fairness_max_deviation: float
    timeline_15m: list[TimelineRatePoint] = Field(default_factory=list)


@router.get("/parameters")
async def get_parameters(db: AsyncSession = Depends(session)) -> list[dict[str, Any]]:
    rows = (
        await db.scalars(
            select(ParameterDefinition).order_by(
                ParameterDefinition.entity, ParameterDefinition.key
            )
        )
    ).all()
    return [
        dict(
            id=r.id,
            entity=r.entity,
            key=r.key,
            label=r.label,
            data_type=r.data_type,
            dictionary_id=r.dictionary_id,
            is_system=r.is_system,
        )
        for r in rows
    ]


@router.post("/parameters", status_code=201)
async def create_parameter(
    body: ParameterIn, db: AsyncSession = Depends(session)
) -> dict[str, Any]:
    if body.entity not in {"order", "executor"} or body.data_type not in {
        "string",
        "number",
        "boolean",
        "date",
        "enum",
        "string_array",
    }:
        raise HTTPException(422, "unsupported parameter entity or type")
    if body.data_type in {"enum", "string_array"} and body.dictionary_id is None:
        raise HTTPException(422, "enum and string_array parameters require a dictionary")
    if body.dictionary_id is not None and await db.get(Dictionary, body.dictionary_id) is None:
        raise HTTPException(422, "dictionary not found")
    if await db.scalar(
        select(ParameterDefinition.id).where(
            ParameterDefinition.entity == body.entity, ParameterDefinition.key == body.key
        )
    ):
        raise HTTPException(409, "parameter already exists")
    row = ParameterDefinition(**body.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, **body.model_dump()}


@router.delete("/parameters/{parameter_id}")
async def delete_parameter(
    parameter_id: int, db: AsyncSession = Depends(session)
) -> dict[str, bool]:
    row = await db.get(ParameterDefinition, parameter_id)
    if row is None:
        raise HTTPException(404, "parameter not found")
    if row.is_system:
        raise HTTPException(409, "system parameters cannot be removed")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.put("/parameters/{parameter_id}")
async def update_parameter(
    parameter_id: int, body: ParameterIn, db: AsyncSession = Depends(session)
) -> dict[str, Any]:
    row = await db.get(ParameterDefinition, parameter_id)
    if row is None:
        raise HTTPException(404, "parameter not found")
    if row.is_system and (body.key != row.key or body.entity != row.entity):
        raise HTTPException(409, "system parameter key and entity cannot change")
    if body.entity not in {"order", "executor"} or body.data_type not in {
        "string",
        "number",
        "boolean",
        "date",
        "enum",
        "string_array",
    }:
        raise HTTPException(422, "unsupported parameter entity or type")
    if body.data_type in {"enum", "string_array"} and body.dictionary_id is None:
        raise HTTPException(422, "enum and string_array parameters require a dictionary")
    if body.dictionary_id is not None and await db.get(Dictionary, body.dictionary_id) is None:
        raise HTTPException(422, "dictionary not found")
    if await db.scalar(
        select(ParameterDefinition.id).where(
            ParameterDefinition.entity == body.entity,
            ParameterDefinition.key == body.key,
            ParameterDefinition.id != parameter_id,
        )
    ):
        raise HTTPException(409, "parameter already exists")
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    await db.commit()
    return {"id": parameter_id, **body.model_dump()}


@router.get("/rules")
async def get_rules(db: AsyncSession = Depends(session)) -> list[dict[str, Any]]:
    rows = (await db.scalars(select(Rule).order_by(Rule.priority, Rule.id))).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "kind": r.kind,
            "condition": r.condition,
            "effect": r.effect,
            "priority": r.priority,
            "enabled": r.enabled,
            "null_policy": r.null_policy,
        }
        for r in rows
    ]


@router.post("/rules", status_code=201)
async def create_rule(body: RuleIn, db: AsyncSession = Depends(session)) -> dict[str, Any]:
    await require_valid_rule(body.condition, body.null_policy, db)
    if body.null_policy not in {"pass", "fail"}:
        raise HTTPException(422, "null_policy must be pass or fail")
    if body.kind not in {"filter", "order_weight", "executor_capacity", "score_bonus"}:
        raise HTTPException(422, "unsupported rule kind")
    row = Rule(**body.model_dump())
    db.add(row)
    await db.flush()
    await retry_unassignable(db)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, **body.model_dump()}


@router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: int, body: RuleIn, db: AsyncSession = Depends(session)
) -> dict[str, Any]:
    await require_valid_rule(body.condition, body.null_policy, db)
    row = await db.get(Rule, rule_id)
    if row is None:
        raise HTTPException(404, "rule not found")
    if body.null_policy not in {"pass", "fail"}:
        raise HTTPException(422, "null_policy must be pass or fail")
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    await retry_unassignable(db)
    await db.commit()
    return {"id": rule_id, **body.model_dump()}


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: int, db: AsyncSession = Depends(session)) -> dict[str, bool]:
    row = await db.get(Rule, rule_id)
    if row is None:
        raise HTTPException(404, "rule not found")
    await db.delete(row)
    await retry_unassignable(db)
    await db.commit()
    return {"ok": True}


@router.patch("/rules/{rule_id}/toggle")
async def toggle_rule(rule_id: int, db: AsyncSession = Depends(session)) -> dict[str, bool]:
    row = await db.get(Rule, rule_id)
    if row is None:
        raise HTTPException(404, "rule not found")
    row.enabled = not row.enabled
    await retry_unassignable(db)
    await db.commit()
    return {"enabled": row.enabled}


@router.post("/rules/validate")
async def validate_rule_api(
    body: dict[str, Any], db: AsyncSession = Depends(session)
) -> dict[str, Any]:
    condition = body.get("condition", body)
    try:
        await validate_rule(condition, str(body.get("null_policy", "fail")), db)
        return {"valid": True}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/rules/dry-run")
async def dry_run(
    body: dict[str, Any], db: AsyncSession = Depends(session)
) -> list[dict[str, Any]]:
    await require_valid_rule(body["condition"], str(body.get("null_policy", "fail")), db)
    predicate = compile_condition(body["condition"])
    order_attrs = body.get("order", {})
    rows = (await db.scalars(select(Executor).order_by(Executor.id))).all()
    return [
        {
            "executor_id": e.id,
            "passed": bool(
                e.is_active and predicate({"order": order_attrs, "executor": e.attributes})
            ),
        }
        for e in rows
    ]


def _condition_leaves(node: dict[str, Any]) -> list[tuple[str, str, list[str]]]:
    if "all" in node or "any" in node or "rules" in node:
        children = node.get("all", node.get("any", node.get("rules", [])))
        return [leaf for child in children for leaf in _condition_leaves(child)]
    if "not" in node and isinstance(node["not"], dict):
        return _condition_leaves(node["not"])
    left = node.get("left")
    path = node.get("field")
    if path is None and isinstance(left, dict):
        path = left.get("ref")
    if not isinstance(path, str):
        return []
    operator = str(node.get("op", ""))
    raw = node.get("value", node.get("right"))
    references: list[str] = []

    def find_refs(value: Any) -> None:
        if isinstance(value, dict):
            ref = value.get("field", value.get("ref"))
            if isinstance(ref, str):
                references.append(ref)
            else:
                for nested in value.values():
                    find_refs(nested)
        elif isinstance(value, list):
            for nested in value:
                find_refs(nested)

    find_refs(raw)
    return [(path, operator, references)]


async def validate_rule(node: dict[str, Any], null_policy: str, db: AsyncSession) -> None:
    if null_policy not in {"pass", "fail"}:
        raise ValueError("null_policy must be pass or fail")
    compile_condition(node, null_policy)
    rows = (await db.scalars(select(ParameterDefinition))).all()
    catalog = {f"{row.entity}.{row.key}": row for row in rows}
    string_operators = {"starts_with", "ends_with", "contains_substr", "regex"}
    array_operators = {"contains", "contains_any", "contains_all", "intersects", "is_empty"}
    numeric_or_date_operators = {"between", "within_last"}
    for path, operator, value_refs in _condition_leaves(node):
        field = catalog.get(path)
        if field is None:
            raise ValueError(f"unknown parameter reference: {path}")
        if operator in string_operators and field.data_type not in {"string", "enum"}:
            raise ValueError(f"{operator} requires a string parameter: {path}")
        if operator in array_operators and field.data_type not in {"enum", "string_array"}:
            raise ValueError(f"{operator} requires an enum or string_array parameter: {path}")
        if operator in numeric_or_date_operators:
            allowed = {"date"} if operator == "within_last" else {"number", "date"}
            if field.data_type not in allowed:
                raise ValueError(f"{operator} is incompatible with {field.data_type}: {path}")
        for reference in value_refs:
            target = catalog.get(reference)
            if target is None:
                raise ValueError(f"unknown parameter reference: {reference}")
            if target.data_type != field.data_type:
                raise ValueError(
                    f"incompatible parameter types at {path}: "
                    f"{field.data_type} vs {target.data_type}"
                )


async def require_valid_rule(node: dict[str, Any], null_policy: str, db: AsyncSession) -> None:
    try:
        await validate_rule(node, null_policy, db)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/dictionaries")
async def get_dictionaries(db: AsyncSession = Depends(session)) -> list[dict[str, Any]]:
    rows = (await db.scalars(select(Dictionary).order_by(Dictionary.code))).all()
    result = []
    for row in rows:
        items = (
            await db.scalars(
                select(DictionaryItem)
                .where(DictionaryItem.dictionary_id == row.id)
                .order_by(DictionaryItem.value)
            )
        ).all()
        result.append(
            {
                "id": row.id,
                "code": row.code,
                "label": row.label,
                "items": [{"value": item.value, "label": item.label} for item in items],
            }
        )
    return result


@router.post("/dictionaries", status_code=201)
async def create_dictionary(
    body: DictionaryIn, db: AsyncSession = Depends(session)
) -> dict[str, Any]:
    if await db.scalar(select(Dictionary.id).where(Dictionary.code == body.code)):
        raise HTTPException(409, "dictionary code already exists")
    row = Dictionary(**body.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, **body.model_dump()}


@router.delete("/dictionaries/{dictionary_id}")
async def delete_dictionary(
    dictionary_id: int, db: AsyncSession = Depends(session)
) -> dict[str, bool]:
    row = await db.get(Dictionary, dictionary_id)
    if row is None:
        raise HTTPException(404, "dictionary not found")
    items = (
        await db.scalars(
            select(DictionaryItem).where(DictionaryItem.dictionary_id == dictionary_id)
        )
    ).all()
    for item in items:
        await db.delete(item)
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.put("/dictionaries/{dictionary_id}")
async def update_dictionary(
    dictionary_id: int, body: DictionaryIn, db: AsyncSession = Depends(session)
) -> dict[str, Any]:
    row = await db.get(Dictionary, dictionary_id)
    if row is None:
        raise HTTPException(404, "dictionary not found")
    if await db.scalar(
        select(Dictionary.id).where(Dictionary.code == body.code, Dictionary.id != dictionary_id)
    ):
        raise HTTPException(409, "dictionary code already exists")
    row.code, row.label = body.code, body.label
    await db.commit()
    return {"id": row.id, **body.model_dump()}


@router.post("/dictionaries/{dictionary_id}/items", status_code=201)
async def add_dictionary_item(
    dictionary_id: int, body: ItemIn, db: AsyncSession = Depends(session)
) -> dict[str, Any]:
    if await db.get(Dictionary, dictionary_id) is None:
        raise HTTPException(404, "dictionary not found")
    if await db.scalar(
        select(DictionaryItem.id).where(
            DictionaryItem.dictionary_id == dictionary_id, DictionaryItem.value == body.value
        )
    ):
        raise HTTPException(409, "dictionary value already exists")
    row = DictionaryItem(dictionary_id=dictionary_id, **body.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, **body.model_dump()}


@router.delete("/dictionaries/{dictionary_id}/items/{item_id}")
async def delete_dictionary_item(
    dictionary_id: int, item_id: int, db: AsyncSession = Depends(session)
) -> dict[str, bool]:
    row = await db.get(DictionaryItem, item_id)
    if row is None or row.dictionary_id != dictionary_id:
        raise HTTPException(404, "dictionary item not found")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.put("/dictionaries/{dictionary_id}/items/{item_id}")
async def update_dictionary_item(
    dictionary_id: int, item_id: int, body: ItemIn, db: AsyncSession = Depends(session)
) -> dict[str, Any]:
    row = await db.get(DictionaryItem, item_id)
    if row is None or row.dictionary_id != dictionary_id:
        raise HTTPException(404, "dictionary item not found")
    if await db.scalar(
        select(DictionaryItem.id).where(
            DictionaryItem.dictionary_id == dictionary_id,
            DictionaryItem.value == body.value,
            DictionaryItem.id != item_id,
        )
    ):
        raise HTTPException(409, "dictionary value already exists")
    row.value, row.label = body.value, body.label
    await db.commit()
    return {"id": item_id, **body.model_dump()}


@router.get("/strategy")
async def get_strategy(db: AsyncSession = Depends(session)) -> dict[str, Any]:
    row = await db.get(StrategySettings, 1)
    return (
        {
            "mode": row.mode,
            "alpha": float(row.alpha),
            "beta": float(row.beta),
            "gamma": float(row.gamma),
        }
        if row
        else StrategyIn().model_dump()
    )


@router.put("/strategy")
async def set_strategy(body: StrategyIn, db: AsyncSession = Depends(session)) -> dict[str, Any]:
    if body.mode not in {"open_load", "cumulative_fair"}:
        raise HTTPException(422, "unsupported strategy mode")
    row = await db.get(StrategySettings, 1)
    if row is None:
        row = StrategySettings(id=1, **body.model_dump())
        db.add(row)
    else:
        for key, value in body.model_dump().items():
            setattr(row, key, value)
    await db.commit()
    return body.model_dump()


@router.get("/orders/{order_id}/explain")
async def explain(order_id: int, db: AsyncSession = Depends(session)) -> dict[str, Any]:
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "order not found")
    logs = (
        await db.scalars(
            select(AssignmentLog)
            .where(AssignmentLog.order_id == order_id)
            .order_by(AssignmentLog.id)
        )
    ).all()
    decisions = list(
        (
            await db.scalars(
                select(CandidateDecision)
                .where(CandidateDecision.order_id == order.id)
                .order_by(CandidateDecision.id.desc())
                .limit(500)
            )
        ).all()
    )
    latest: dict[int, CandidateDecision] = {}
    for decision in decisions:
        latest.setdefault(decision.executor_id, decision)
    return {
        "order_id": order.id,
        "state": order.assignment_state,
        "executor_id": order.executor_id,
        "rejection_reason": order.rejection_reason,
        "attributes": order.attributes,
        "candidates": [
            {
                "executor_id": row.executor_id,
                "passed": row.passed,
                "reason": row.reason,
                "score": float(row.score) if row.score is not None else None,
                "detail": row.detail,
                "decided_at": row.created_at,
            }
            for row in latest.values()
        ],
        "history": [
            {
                "executor_id": log.executor_id,
                "reason": log.reason,
                "detail": log.detail,
                "at": log.created_at,
            }
            for log in logs
        ],
    }


@router.get("/analytics/summary", response_model=AnalyticsSummary)
async def analytics_summary(db: AsyncSession = Depends(session)) -> AnalyticsSummary:
    total = int(await db.scalar(select(func.count()).select_from(Order)) or 0)
    assigned = int(
        await db.scalar(
            select(func.count()).select_from(Order).where(Order.executor_id.is_not(None))
        )
        or 0
    )
    pending = int(
        await db.scalar(
            select(func.count()).select_from(Order).where(Order.assignment_state == "pending")
        )
        or 0
    )
    unassignable = int(
        await db.scalar(
            select(func.count()).select_from(Order).where(Order.assignment_state == "unassignable")
        )
        or 0
    )
    active = int(
        await db.scalar(
            select(func.count()).select_from(Executor).where(Executor.is_active.is_(True))
        )
        or 0
    )
    now = datetime.now(timezone.utc)
    minute_ago = now - timedelta(minutes=1)
    since_15 = now - timedelta(minutes=15)
    recent = (await db.scalars(select(Order).where(Order.received_at >= minute_ago))).all()
    window_orders = list(
        (
            await db.scalars(
                select(Order).where(Order.received_at >= since_15).order_by(Order.received_at)
            )
        ).all()
    )
    series: dict[str, dict[str, float | str]] = {}
    for item in window_orders:
        bucket = item.received_at.replace(second=0, microsecond=0).isoformat()
        point = series.setdefault(bucket, {"bucket": bucket, "rps_in": 0.0, "rps_assigned": 0.0})
        point["rps_in"] = float(point["rps_in"]) + 1 / 60
        if item.executor_id is not None:
            point["rps_assigned"] = float(point["rps_assigned"]) + 1 / 60
    completed = list(
        (
            await db.scalars(
                select(Order)
                .where(Order.confirmed_at.is_not(None))
                .order_by(Order.confirmed_at.desc())
                .limit(5000)
            )
        ).all()
    )
    latencies = sorted(
        max(0.0, (item.confirmed_at - item.received_at).total_seconds())
        for item in completed
        if item.confirmed_at is not None
    )
    p50 = latencies[min(len(latencies) - 1, int((len(latencies) - 1) * 0.50))] if latencies else 0.0
    p95 = latencies[min(len(latencies) - 1, int((len(latencies) - 1) * 0.95))] if latencies else 0.0
    dead = int(
        await db.scalar(select(func.count()).select_from(Outbox).where(Outbox.status == "dead"))
        or 0
    )
    outbox_pending = int(
        await db.scalar(select(func.count()).select_from(Outbox).where(Outbox.status == "new")) or 0
    )
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        try:
            pending_summary = await redis.xpending("bal.orders", "workers")
            queue_lag = int(pending_summary["pending"])
        except Exception:
            queue_lag = 0
    finally:
        await redis.aclose()
    fair = await fairness(window="today", db=db)
    outbox_pending_metric.set(outbox_pending)
    dead_letter_metric.set(dead)
    stream_pending_metric.set(queue_lag)
    fairness_metric.set(fair["max_deviation"])
    for executor in await db.scalars(select(Executor)):
        executor_open_weight.labels(str(executor.id)).set(float(executor.open_weight))
        executor_day_weight.labels(str(executor.id)).set(float(executor.day_weight))
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        stream_length = int(await redis.xlen("bal.orders"))
    except Exception:
        stream_length = 0
    finally:
        await redis.aclose()
    timeline_points = [
        TimelineRatePoint(
            bucket=datetime.fromisoformat(str(point["bucket"])),
            rps_in=float(point["rps_in"]),
            rps_assigned=float(point["rps_assigned"]),
        )
        for point in series.values()
    ]
    return AnalyticsSummary(
        orders=total,
        assigned=assigned,
        pending=pending,
        unassignable=unassignable,
        active_executors=active,
        rps_in=len(recent) / 60,
        rps_assigned=sum(item.executor_id is not None for item in recent) / 60,
        rps_in_per_minute=len(recent),
        rps_assigned_per_minute=sum(item.executor_id is not None for item in recent),
        p95_latency_seconds=p95,
        p50_latency_seconds=p50,
        outbox_pending=int(
            await db.scalar(select(func.count()).select_from(Outbox).where(Outbox.status == "new"))
            or 0
        ),
        stream_length=stream_length,
        queue_lag=queue_lag,
        dlq=dead,
        fairness_max_deviation=fair["max_deviation"],
        timeline_15m=timeline_points,
    )


@router.get("/analytics/timeline")
async def timeline(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    bucket: str = "1h",
    group_by: str = "executor",
    db: AsyncSession = Depends(session),
) -> list[dict[str, Any]]:
    if bucket not in {"1m", "5m", "1h"}:
        raise HTTPException(422, "bucket must be 1m, 5m or 1h")
    start = from_ or datetime.now(timezone.utc) - timedelta(days=1)
    end = to or datetime.now(timezone.utc)
    rows = (
        await db.scalars(
            select(Order)
            .where(Order.received_at >= start, Order.received_at <= end)
            .order_by(Order.received_at)
        )
    ).all()
    groups: dict[str, int] = {}
    seconds = {"1m": 60, "5m": 300, "1h": 3600}[bucket]
    for order in rows:
        stamp = order.received_at.replace(second=0, microsecond=0)
        minute = (stamp.minute // (seconds // 60)) * (seconds // 60)
        stamp = stamp.replace(minute=minute) if seconds < 3600 else stamp.replace(minute=0)
        attr = {
            "executor": str(order.executor_id),
            "type": str(order.attributes.get("order_type", "unknown")),
            "subject": str(order.attributes.get("subject", "unknown")),
            "state": order.assignment_state,
        }.get(group_by)
        if attr is None:
            raise HTTPException(422, "invalid group_by")
        key = f"{stamp.isoformat()}|{attr}"
        groups[key] = groups.get(key, 0) + 1
    return [
        {"bucket": key.split("|", 1)[0], "group": key.split("|", 1)[1], "count": value}
        for key, value in groups.items()
    ]


@router.get("/analytics/fairness")
async def fairness(db: AsyncSession = Depends(session), window: str = "today") -> dict[str, Any]:
    if window not in {"1h", "today"}:
        raise HTTPException(422, "window must be 1h or today")
    rows = (await db.scalars(select(Executor).where(Executor.is_active.is_(True)))).all()
    if not rows:
        return {"max_deviation": 0, "p95_deviation": 0, "executors": []}
    strategy = await db.get(StrategySettings, 1)
    use_open = strategy is not None and strategy.mode == "open_load"
    if window == "1h":
        start = datetime.now(timezone.utc) - timedelta(hours=1)
        recent_assignments = list(
            (await db.scalars(select(AssignmentLog).where(AssignmentLog.created_at >= start))).all()
        )
        counts: dict[int, float] = {}
        for assignment in recent_assignments:
            if assignment.executor_id is not None:
                counts[assignment.executor_id] = counts.get(assignment.executor_id, 0.0) + 1.0
    else:
        today = datetime.now(timezone.utc).astimezone(ZoneInfo(settings.limit_tz)).date()
        usages = list(
            (
                await db.scalars(
                    select(ExecutorDailyUsage).where(ExecutorDailyUsage.day_date == today)
                )
            ).all()
        )
        counts = {usage.executor_id: float(usage.assigned_weight) for usage in usages}
    pools: dict[str, list[Executor]] = {}
    for executor in rows:
        signature = "|".join(
            str(executor.attributes.get(key, "*"))
            for key in ("client_msp", "executor_msp", "order_type", "subject", "vip")
        )
        pools.setdefault(signature, []).append(executor)
    details: list[dict[str, Any]] = []
    deviations: list[float] = []
    for signature, members in pools.items():
        loads = [
            (
                float(row.open_weight)
                if use_open and window == "today"
                else counts.get(row.id, 0.0)
                if window == "1h"
                else counts.get(row.id, 0.0) / max(float(row.daily_limit or row.day_count or 1), 1)
            )
            / max(float(row.capacity), 0.001)
            for row in members
        ]
        mean = sum(loads) / len(loads)
        pool_deviations = [abs(load - mean) / mean if mean else 0.0 for load in loads]
        deviations.extend(pool_deviations)
        details.extend(
            {"id": member.id, "pool": signature, "load": load, "deviation": deviation}
            for member, load, deviation in zip(members, loads, pool_deviations, strict=True)
        )
    deviations.sort()
    p95 = deviations[min(len(deviations) - 1, int(len(deviations) * 0.95))]
    return {
        "max_deviation": max(deviations),
        "p95_deviation": p95,
        "executors": details,
    }


@router.get("/analytics/export.json")
async def export_json(db: AsyncSession = Depends(session)) -> dict[str, Any]:
    return {
        "summary": await analytics_summary(db),
        "executors": await _executor_rows(db),
        "orders": await _order_rows(db),
        "timeline": await timeline(from_=None, to=None, bucket="1h", group_by="executor", db=db),
        "assignments": await _assignment_rows(db),
        "fairness": await fairness(window="today", db=db),
    }


async def _executor_rows(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db.scalars(select(Executor).order_by(Executor.id))).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "active": r.is_active,
            "open_count": r.open_count,
            "open_weight": float(r.open_weight),
            "capacity": float(r.capacity),
            "day_count": r.day_count,
            "day_weight": float(r.day_weight),
            "daily_limit": r.daily_limit,
        }
        for r in rows
    ]


async def _order_rows(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db.scalars(select(Order).order_by(Order.id))).all()
    return [
        {
            "id": r.id,
            "executor_id": r.executor_id,
            "status": r.status,
            "assignment_state": r.assignment_state,
            "received_at": r.received_at.isoformat(),
        }
        for r in rows
    ]


async def _assignment_rows(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db.scalars(select(AssignmentLog).order_by(AssignmentLog.id))).all()
    return [
        {
            "id": row.id,
            "order_id": row.order_id,
            "executor_id": row.executor_id,
            "reason": row.reason,
            "detail": row.detail,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.get("/analytics/export.xlsx")
async def export_xlsx(db: AsyncSession = Depends(session)) -> StreamingResponse:
    workbook = Workbook()
    fair = await fairness(window="today", db=db)
    summary = (await analytics_summary(db)).model_dump()
    sheets: list[tuple[str, list[dict[str, Any]]]] = [
        ("Summary", [summary]),
        ("Executors", await _executor_rows(db)),
        (
            "Timeline",
            await timeline(from_=None, to=None, bucket="1h", group_by="executor", db=db),
        ),
        ("Fairness", fair["executors"]),
        ("Assignments", await _assignment_rows(db)),
    ]
    for title, records in sheets:
        sheet = workbook.active if title == "Summary" else workbook.create_sheet(title)
        sheet.title = title
        if records:
            sheet.append(list(records[0].keys()))
            for record in records:
                sheet.append(
                    [
                        str(value) if isinstance(value, (dict, list)) else value
                        for value in record.values()
                    ]
                )
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=executor-balancer.xlsx"},
    )


async def live_snapshot() -> dict[str, Any]:
    async with Session() as db:
        stats = await analytics_summary(db)
        exes = await _executor_rows(db)
        recent = (
            await db.scalars(select(Order).order_by(Order.received_at.desc()).limit(20))
        ).all()
        events = [
            {
                "id": order.id,
                "executor_id": order.executor_id,
                "assignment_state": order.assignment_state,
                "status": order.status,
                "attributes": order.attributes,
            }
            for order in reversed(recent)
        ]
        return {**stats.model_dump(), "per_executor": exes, "last_events": events}


async def live_loop(send: Any) -> None:
    while True:
        await send(await live_snapshot())
        await asyncio.sleep(1)


@router.get("/audit")
async def audit(limit: int = 200, db: AsyncSession = Depends(session)) -> list[dict[str, Any]]:
    rows = (
        await db.scalars(
            select(AssignmentLog).order_by(AssignmentLog.id.desc()).limit(min(limit, 1000))
        )
    ).all()
    return [
        {
            "id": row.id,
            "order_id": row.order_id,
            "executor_id": row.executor_id,
            "reason": row.reason,
            "detail": row.detail,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/dlq")
async def get_dlq(db: AsyncSession = Depends(session)) -> dict[str, Any]:
    rows = (
        await db.scalars(select(Outbox).where(Outbox.status == "dead").order_by(Outbox.id))
    ).all()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        stream_rows = await redis.xrevrange("bal.orders.dlq", count=100)
    finally:
        await redis.aclose()
    return {
        "outbox": [
            {
                "id": row.id,
                "order_id": row.order_id,
                "executor_id": row.executor_id,
                "attempts": row.attempts,
                "status": row.status,
            }
            for row in rows
        ],
        "stream": [{"id": stream_id, **fields} for stream_id, fields in stream_rows],
    }


@router.post("/dlq/outbox/{outbox_id}/retry")
async def retry_dlq(outbox_id: int, db: AsyncSession = Depends(session)) -> dict[str, bool]:
    row = await db.get(Outbox, outbox_id)
    if row is None or row.status != "dead":
        raise HTTPException(404, "dead outbox row not found")
    row.status, row.attempts = "new", 0
    row.retry_at, row.last_error = None, None
    order = await db.get(Order, row.order_id)
    if order is not None:
        order.assignment_state = "reserved"
    await db.commit()
    return {"ok": True}


@router.post("/dlq/stream/{message_id}/retry")
async def retry_stream_dlq(message_id: str, db: AsyncSession = Depends(session)) -> dict[str, bool]:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        message = await redis.xrange("bal.orders.dlq", min=message_id, max=message_id)
        if not message:
            raise HTTPException(404, "dead stream event not found")
        fields = message[0][1]
        order_id = fields.get("order_id")
        if order_id is None:
            raise HTTPException(422, "DLQ event has no order_id")
        await redis.xadd("bal.orders", {"order_id": order_id})
        order = await db.get(Order, int(order_id))
        if order is not None:
            order.assignment_state = "pending"
            await db.commit()
    finally:
        await redis.aclose()
    return {"ok": True}


@router.get("/orders/{order_id}")
async def get_order_detail(order_id: int, db: AsyncSession = Depends(session)) -> dict[str, Any]:
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "order not found")
    logs = (
        await db.scalars(
            select(AssignmentLog)
            .where(AssignmentLog.order_id == order.id)
            .order_by(AssignmentLog.id)
        )
    ).all()
    return {
        "id": order.id,
        "parent_id": order.parent_id,
        "status": order.status,
        "executor_id": order.executor_id,
        "assignment_state": order.assignment_state,
        "rejection_reason": order.rejection_reason,
        "attributes": order.attributes,
        "candidates": order.attributes.get("candidate_rejections", {}),
        "history": [
            {
                "executor_id": row.executor_id,
                "reason": row.reason,
                "detail": row.detail,
                "created_at": row.created_at,
            }
            for row in logs
        ],
    }


@router.get("/executors/{executor_id}")
async def get_executor_detail(
    executor_id: int, db: AsyncSession = Depends(session)
) -> dict[str, Any]:
    executor = await db.get(Executor, executor_id)
    if executor is None:
        raise HTTPException(404, "executor not found")
    logs = (
        await db.scalars(
            select(AssignmentLog)
            .where(AssignmentLog.executor_id == executor.id)
            .order_by(AssignmentLog.id.desc())
            .limit(100)
        )
    ).all()
    return {
        "id": executor.id,
        "name": executor.name,
        "is_active": executor.is_active,
        "attributes": executor.attributes,
        "open_count": executor.open_count,
        "open_weight": float(executor.open_weight),
        "daily_limit": executor.daily_limit,
        "day_count": executor.day_count,
        "day_weight": float(executor.day_weight),
        "history": [
            {"order_id": row.order_id, "reason": row.reason, "detail": row.detail} for row in logs
        ],
    }


@router.get("/dashboard/timeline", response_model=list[TimelineRatePoint])
async def dashboard_timeline(
    db: AsyncSession = Depends(session),
) -> list[dict[str, Any]]:
    return await timeline(
        from_=datetime.now(timezone.utc) - timedelta(minutes=15),
        to=datetime.now(timezone.utc),
        bucket="1m",
        group_by="state",
        db=db,
    )
