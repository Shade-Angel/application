import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import ORJSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field, field_validator
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import (
    live_loop,
)
from app.admin import (
    router as admin_router,
)
from app.config import settings
from app.db import engine, session
from app.dsl import compile_condition
from app.matching import retry_unassignable
from app.metrics import (
    assignment_latency,
    assignments_confirmed,
    orders_ingested,
)
from app.models import (
    Executor,
    Order,
    ProcessedEvent,
    Rule,
    StreamEvent,
)

logging.basicConfig(format="%(message)s", level=logging.INFO)
structlog.configure(processors=[structlog.processors.JSONRenderer()])


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


app = FastAPI(
    title="Executor Balancer",
    version="0.1.0",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)
app.include_router(admin_router)


class ExecutorEvent(BaseModel):
    id: int
    first_name: str = ""
    last_name: str = ""
    middle_name: str | None = None
    status: str = "active"
    settings: dict[str, Any] = Field(default_factory=dict, validation_alias="settings")
    source_updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("source_updated_at")
    @classmethod
    def source_time_is_utc(cls, value: datetime) -> datetime:
        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )

    @field_validator("status")
    @classmethod
    def valid_user_status(cls, value: str) -> str:
        if value not in {"active", "inactive"}:
            raise ValueError("status must be active or inactive")
        return value


class OrderEvent(BaseModel):
    id: int
    parent_id: int | None = None
    status: str = "processed"
    sum: int | float = Field(gt=0, validation_alias="sum")
    client_msp: str | None = None
    executor_msp: str | None = None
    order_type: str
    subject: str
    vip: bool = False
    text: str | None = None
    weight: float = Field(default=1.0, gt=0, le=1000)
    attributes: dict[str, Any] = Field(default_factory=dict)
    user_id: int | None = None
    source_updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("source_updated_at")
    @classmethod
    def source_time_is_utc(cls, value: datetime) -> datetime:
        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready(db: AsyncSession = Depends(session)) -> dict[str, str]:
    await db.execute(select(1))
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis.ping()
    finally:
        await redis.aclose()
    return {"status": "ready"}


@app.post("/ingest/executors")
async def ingest_executor(
    event: ExecutorEvent,
    db: AsyncSession = Depends(session),
    x_event_id: str | None = Header(default=None),
    x_webhook_secret: str | None = Header(default=None),
) -> dict[str, bool]:
    verify_webhook(x_webhook_secret)
    if event.status not in {"active", "inactive"}:
        raise HTTPException(422, "status must be active or inactive")
    if not await claim_event(db, x_event_id):
        return {"ok": True, "duplicate": True}
    existing = await db.scalar(select(Executor).where(Executor.id == event.id).with_for_update())
    if existing is not None and existing.source_updated_at >= event.source_updated_at:
        await db.commit()
        return {"ok": True, "stale": True}
    attrs = {
        **event.settings,
        "first_name": event.first_name,
        "last_name": event.last_name,
        "middle_name": event.middle_name,
        "status": event.status,
    }
    name = " ".join(
        part for part in (event.last_name, event.first_name, event.middle_name or "") if part
    )
    if existing is None:
        db.add(
            Executor(
                id=event.id,
                name=name,
                is_active=event.status == "active",
                attributes=attrs,
                daily_limit=event.settings.get("max_daily_limit"),
                source_updated_at=event.source_updated_at,
            )
        )
    else:
        existing.name, existing.is_active, existing.attributes = (
            name,
            event.status == "active",
            attrs,
        )
        existing.daily_limit = event.settings.get("max_daily_limit")
        existing.source_updated_at = event.source_updated_at
    if event.status == "inactive" and settings.reassign_on_deactivate:
        existing_orders = list(
            (
                await db.scalars(
                    select(Order)
                    .where(Order.executor_id == event.id, Order.holds_slot.is_(True))
                    .order_by(Order.id)
                    .with_for_update()
                )
            ).all()
        )
        assigned_orders = [order for order in existing_orders if order.holds_slot]
        for order in assigned_orders:
            if existing is not None:
                existing.open_count = max(0, existing.open_count - 1)
                existing.open_weight = max(
                    Decimal(0), Decimal(existing.open_weight) - Decimal(order.weight)
                )
            order.holds_slot = False
            order.assignment_state = "pending"
            db.add(StreamEvent(order_id=order.id))
    await retry_unassignable(db)
    await db.commit()
    return {"ok": True}


@app.post("/ingest/orders")
async def ingest_order(
    event: OrderEvent,
    db: AsyncSession = Depends(session),
    x_event_id: str | None = Header(default=None),
    x_webhook_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_webhook(x_webhook_secret)
    allowed_statuses = {
        *settings.open_statuses.split(","),
        *settings.closed_statuses.split(","),
        settings.review_status.strip(),
    }
    if event.status not in allowed_statuses:
        raise HTTPException(422, "unsupported order status")
    if not await claim_event(db, x_event_id):
        return {"ok": True, "duplicate": True}
    attrs = {
        "sum": event.sum,
        "client_msp": event.client_msp,
        "executor_msp": event.executor_msp,
        "order_type": event.order_type,
        "subject": event.subject,
        "vip": event.vip,
        "text": event.text,
        "weight": event.weight,
        "user_id": event.user_id,
        **event.attributes,
    }
    order = await db.scalar(select(Order).where(Order.id == event.id).with_for_update())
    if order is not None and order.source_updated_at > event.source_updated_at:
        await db.commit()
        return {"ok": True, "stale": True}
    is_new_order = order is None
    was_open = bool(order and order.status in settings.open_statuses.split(","))
    was_closed = bool(order and order.status in settings.closed_statuses.split(","))
    if order is None:
        order = Order(
            id=event.id,
            parent_id=event.parent_id,
            status=event.status,
            weight=Decimal(str(event.weight)),
            attributes=attrs,
            source_updated_at=event.source_updated_at,
        )
        db.add(order)
    else:
        order.parent_id, order.status, order.attributes = event.parent_id, event.status, attrs
        order.weight = Decimal(str(event.weight))
        order.source_updated_at = event.source_updated_at
    orders_ingested.inc()
    await db.flush()
    if (
        event.status in settings.open_statuses.split(",")
        and not order.holds_slot
        and (is_new_order or was_closed)
    ):
        order.assignment_state = "pending"
        db.add(StreamEvent(order_id=order.id))
        await db.commit()
        return {"ok": True, "assignment_state": "pending"}
    if (
        event.status in settings.closed_statuses.split(",")
        and order.holds_slot
        and order.executor_id
    ):
        executor = await db.get(Executor, order.executor_id)
        if executor:
            executor.open_count = max(0, executor.open_count - 1)
            executor.open_weight = max(
                Decimal(0), Decimal(executor.open_weight) - Decimal(order.weight)
            )
        order.holds_slot = False
        order.assignment_state = "closed"
        await db.commit()
        return {"ok": True}
    if was_open and event.status in settings.closed_statuses.split(",") and not order.holds_slot:
        await db.commit()
        return {"ok": True}
    should_reassign = (
        event.status == settings.review_status.strip()
        and order.executor_id is not None
        and order.holds_slot
        and (not settings.reassign_only_secondary or order.parent_id is not None)
    )
    if event.status == settings.review_status.strip() and order.holds_slot and not should_reassign:
        order.assignment_state = "awaiting_review"
        await db.commit()
        return {"ok": True}
    if should_reassign:
        current = await db.get(Executor, order.executor_id)
        stored_rules = list(
            (
                await db.scalars(select(Rule).where(Rule.enabled.is_(True), Rule.kind == "filter"))
            ).all()
        )
        try:
            rules = [compile_condition(rule.condition, rule.null_policy) for rule in stored_rules]
            rules.extend(
                compile_condition(rule, str(order.attributes.get("null_policy", "fail")))
                for rule in order.attributes.get("rules", [])
            )
            still_eligible = (
                current is not None
                and current.is_active
                and all(
                    rule({"order": order.attributes, "executor": current.attributes})
                    for rule in rules
                )
            )
        except ValueError:
            still_eligible = False
        if not still_eligible:
            if current is not None:
                current.open_count = max(0, current.open_count - 1)
                current.open_weight = max(
                    Decimal(0), Decimal(current.open_weight) - Decimal(order.weight)
                )
            order.holds_slot = False
            order.assignment_state = "pending"
            await db.flush()
            db.add(StreamEvent(order_id=order.id))
    elif order.holds_slot and event.status in settings.open_statuses.split(","):
        current = await db.get(Executor, order.executor_id) if order.executor_id else None
        if current is not None:
            current.open_count = max(0, current.open_count - 1)
            current.open_weight = max(
                Decimal(0), Decimal(current.open_weight) - Decimal(order.weight)
            )
        order.executor_id = None
        order.holds_slot = False
        order.assignment_state = "pending"
        await db.flush()
        db.add(StreamEvent(order_id=order.id))
    await db.commit()
    return {"ok": True}


@app.post("/ingest/assignment-confirmed")
async def assignment_confirmed(
    payload: dict[str, Any],
    db: AsyncSession = Depends(session),
    x_webhook_secret: str | None = Header(default=None),
) -> dict[str, bool]:
    verify_webhook(x_webhook_secret)
    order = await db.get(Order, int(payload["order_id"]))
    if order is None:
        raise HTTPException(404, "order not found")
    executor_id = int(payload["executor_id"])
    if order.executor_id != executor_id:
        raise HTTPException(409, "assignment confirmation does not match current executor")
    if order.assignment_state == "confirmed":
        return {"ok": True, "duplicate": True}
    from app.models import Outbox

    outboxes = (
        await db.scalars(
            select(Outbox).where(Outbox.order_id == order.id, Outbox.executor_id == executor_id)
        )
    ).all()
    if not outboxes:
        raise HTTPException(404, "assignment outbox not found")
    for outbox in outboxes:
        if outbox.status == "confirmed":
            continue
        outbox.status = "confirmed"
    order.assignment_state = "confirmed"
    order.confirmed_at = datetime.now(timezone.utc)
    assignments_confirmed.inc()
    assignment_latency.observe((order.confirmed_at - order.received_at).total_seconds())
    await db.commit()
    return {"ok": True}


@app.get("/api/orders")
async def orders(
    state: str | None = None,
    executor_id: int | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    db: AsyncSession = Depends(session),
) -> list[dict[str, Any]]:
    statement = select(Order)
    if state:
        statement = statement.where(Order.assignment_state == state)
    if executor_id is not None:
        statement = statement.where(Order.executor_id == executor_id)
    if from_:
        statement = statement.where(Order.received_at >= from_)
    if to:
        statement = statement.where(Order.received_at <= to)
    rows = (await db.scalars(statement.order_by(Order.received_at.desc()).limit(1000))).all()
    return [
        {
            "id": r.id,
            "status": r.status,
            "executor_id": r.executor_id,
            "assignment_state": r.assignment_state,
            "attributes": r.attributes,
            "received_at": r.received_at,
        }
        for r in rows
    ]


@app.get("/api/executors")
async def executors(
    active: bool | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(session),
) -> list[dict[str, Any]]:
    statement = select(Executor)
    if active is not None:
        statement = statement.where(Executor.is_active.is_(active))
    if q:
        statement = statement.where(Executor.name.ilike(f"%{q}%"))
    rows = (await db.scalars(statement.order_by(Executor.id))).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "is_active": r.is_active,
            "open_count": r.open_count,
            "open_weight": float(r.open_weight),
            "capacity": float(r.capacity),
            "daily_limit": r.daily_limit,
            "day_count": r.day_count,
            "day_weight": float(r.day_weight),
        }
        for r in rows
    ]


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def verify_webhook(secret: str | None) -> None:
    if secret != settings.webhook_secret:
        raise HTTPException(status_code=401, detail="invalid webhook secret")


async def claim_event(db: AsyncSession, event_id: str | None) -> bool:
    """Atomically claim an event; the claim is committed with its source update."""
    if event_id is None:
        return True
    statement = (
        pg_insert(ProcessedEvent)
        .values(event_id=event_id)
        .on_conflict_do_nothing()
        .returning(ProcessedEvent.event_id)
    )
    return await db.scalar(statement) is not None


@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        await live_loop(websocket.send_json)
    except WebSocketDisconnect:
        return
