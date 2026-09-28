from __future__ import annotations

import asyncio
import itertools
import random
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False)
SETTING_FIELDS = {
    "min_accept_sum",
    "max_accept_sum",
    "min_reject_sum",
    "max_reject_sum",
    "client_msp",
    "executor_msp",
    "order_type",
    "subject",
    "vip",
    "max_daily_limit",
}


async def store_user_settings(
    db: AsyncSession, user_id: int, values: dict[str, Any]
) -> UserSetting:
    row = await db.scalar(select(UserSetting).where(UserSetting.user_id == user_id))
    if row is None:
        row = UserSetting(user_id=user_id)
        db.add(row)
    for name in SETTING_FIELDS:
        value = values.get(name)
        if name.endswith("_sum") or name == "max_daily_limit":
            value = None if value is None else int(value)
        elif name == "vip":
            value = bool(value)
        elif value is not None:
            value = str(value)
        setattr(row, name, value)
    row.extra_settings = {key: value for key, value in values.items() if key not in SETTING_FIELDS}
    return row


class AISBase(DeclarativeBase):
    metadata = MetaData(schema="ais")


class User(AISBase):
    __tablename__ = "ais_users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(255))
    last_name: Mapped[str] = mapped_column(String(255))
    middle_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    source_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class UserSetting(AISBase):
    __tablename__ = "ais_user_settings"
    __table_args__ = (UniqueConstraint("user_id", name="uq_ais_user_settings_user_id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("ais.ais_users.id", ondelete="CASCADE"), nullable=False
    )
    min_accept_sum: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_accept_sum: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    min_reject_sum: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_reject_sum: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    client_msp: Mapped[str | None] = mapped_column(String(255), nullable=True)
    executor_msp: Mapped[str | None] = mapped_column(String(255), nullable=True)
    order_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(128), nullable=True)
    vip: Mapped[bool] = mapped_column(Boolean, default=False)
    max_daily_limit: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    extra_settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class AISOrder(AISBase):
    __tablename__ = "ais_orders"
    __table_args__ = (
        Index("ix_ais_orders_assigned", "executor_id", "status"),
        Index("ix_ais_orders_parent", "parent_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    weight: Mapped[float] = mapped_column(Numeric(8, 3), default=1.0, nullable=False)
    client_msp: Mapped[str | None] = mapped_column(String(255), nullable=True)
    executor_msp: Mapped[str | None] = mapped_column(String(255), nullable=True)
    order_type: Mapped[str] = mapped_column(String(64))
    subject: Mapped[str] = mapped_column(String(128))
    vip: Mapped[bool] = mapped_column(Boolean, default=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="processed")
    executor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    attributes_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    source_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class AISAssignment(AISBase):
    __tablename__ = "ais_assignments"
    __table_args__ = (
        PrimaryKeyConstraint("order_id", "idempotency_key"),
        Index("ix_ais_assignments_order", "order_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False)
    order_id: Mapped[int] = mapped_column(BigInteger)
    executor_id: Mapped[int] = mapped_column(BigInteger)
    idempotency_key: Mapped[str] = mapped_column(String(255))


simulation_tasks: dict[str, asyncio.Task[None]] = {}
simulation_counts = {"orders": 0, "status_changes": 0, "chaos_changes": 0}
SIM_ORDER_ID_START = 2_026_000_000
sim_order_ids = itertools.count(SIM_ORDER_ID_START)
order_simulation_start_lock = asyncio.Lock()


def next_sim_order_id_start(last_order_id: int | None) -> int:
    """Choose a fresh simulator ID even after the AIS emulator restarts."""
    return max(SIM_ORDER_ID_START, (last_order_id or SIM_ORDER_ID_START - 1) + 1)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    for task in simulation_tasks.values():
        task.cancel()
    if simulation_tasks:
        await asyncio.gather(*simulation_tasks.values(), return_exceptions=True)
    simulation_tasks.clear()
    await engine.dispose()


app = FastAPI(title="AIS Emulator", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


class UserInput(BaseModel):
    id: int
    first_name: str
    last_name: str
    middle_name: str | None = None
    status: str = "active"
    settings: dict[str, Any] = Field(default_factory=dict)
    source_updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("source_updated_at")
    @classmethod
    def ensure_utc(cls, value: datetime) -> datetime:
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


class OrderInput(BaseModel):
    id: int
    parent_id: int | None = None
    user_id: int | None = None
    amount: int = Field(gt=0)
    client_msp: str | None = None
    executor_msp: str | None = None
    order_type: str
    subject: str
    vip: bool = False
    text: str | None = None
    weight: float = 1.0
    attributes: dict[str, Any] = Field(default_factory=dict)
    status: str = "processed"
    source_updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("source_updated_at")
    @classmethod
    def ensure_utc(cls, value: datetime) -> datetime:
        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )

    @field_validator("weight")
    @classmethod
    def valid_weight(cls, value: float) -> float:
        if not 0 < value <= 1000:
            raise ValueError("weight must be greater than zero and at most 1000")
        return value

    @field_validator("status")
    @classmethod
    def valid_order_status(cls, value: str) -> str:
        if value not in {"processed", "await", "accept", "reject"}:
            raise ValueError("unsupported order status")
        return value


class UserSettingsInput(BaseModel):
    user_id: int
    settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("settings")
    @classmethod
    def validate_daily_limit(cls, value: dict[str, Any]) -> dict[str, Any]:
        limit = value.get("max_daily_limit")
        if limit is not None and (not isinstance(limit, int) or not 0 <= limit <= 32767):
            raise ValueError("max_daily_limit must be null or between 0 and 32767")
        return value


class OrderStatusInput(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str) -> str:
        if value not in {"processed", "await", "accept", "reject"}:
            raise ValueError("unsupported order status")
        return value


async def webhook(path: str, body: dict[str, Any]) -> None:
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.post(
            settings.balancer_url + path,
            json=jsonable_encoder(body),
            headers={"X-Event-Id": str(uuid.uuid4()), "X-Webhook-Secret": settings.webhook_secret},
        )
        response.raise_for_status()


@app.post("/api/users")
async def create_user(payload: UserInput) -> dict[str, Any]:
    async with Session() as db:
        user = await db.get(User, payload.id)
        if user is not None and user.source_updated_at > payload.source_updated_at:
            event = {
                "id": user.id,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "middle_name": user.middle_name,
                "status": user.status,
                "settings": user.settings_json,
                "source_updated_at": user.source_updated_at,
            }
        else:
            if user is None:
                user = User(
                    id=payload.id,
                    first_name=payload.first_name,
                    last_name=payload.last_name,
                    middle_name=payload.middle_name,
                    status=payload.status,
                    settings_json=payload.settings,
                    source_updated_at=payload.source_updated_at,
                )
                db.add(user)
            else:
                user.first_name, user.last_name = payload.first_name, payload.last_name
                user.middle_name, user.status, user.settings_json = (
                    payload.middle_name,
                    payload.status,
                    payload.settings,
                )
                user.source_updated_at = payload.source_updated_at
            event = payload.model_dump()
            await store_user_settings(db, payload.id, payload.settings)
        await db.commit()
    await webhook("/ingest/executors", event)
    return event


@app.get("/api/users")
async def list_users() -> list[dict[str, Any]]:
    async with Session() as db:
        users = (await db.scalars(select(User).order_by(User.id))).all()
        return [
            {
                "id": u.id,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "status": u.status,
                "settings": u.settings_json,
            }
            for u in users
        ]


@app.get("/api/user-settings")
async def list_user_settings() -> list[dict[str, Any]]:
    async with Session() as db:
        rows = (await db.scalars(select(UserSetting).order_by(UserSetting.user_id))).all()
        return [
            {
                "user_id": row.user_id,
                "settings": {
                    **row.extra_settings,
                    **{name: getattr(row, name) for name in SETTING_FIELDS},
                },
            }
            for row in rows
        ]


@app.get("/api/user-settings/{user_id}")
async def get_user_settings(user_id: int) -> dict[str, Any]:
    async with Session() as db:
        row = await db.scalar(select(UserSetting).where(UserSetting.user_id == user_id))
        if row is None:
            raise HTTPException(404, "user settings not found")
        return {
            "user_id": row.user_id,
            "settings": {
                **row.extra_settings,
                **{name: getattr(row, name) for name in SETTING_FIELDS},
            },
        }


@app.post("/api/user-settings", status_code=201)
async def create_user_settings(payload: UserSettingsInput) -> dict[str, Any]:
    async with Session() as db:
        user = await db.get(User, payload.user_id)
        if user is None:
            raise HTTPException(404, "user not found")
        if await db.scalar(select(UserSetting.id).where(UserSetting.user_id == payload.user_id)):
            raise HTTPException(409, "user settings already exist")
        user.settings_json = payload.settings
        user.source_updated_at = datetime.now(timezone.utc)
        await store_user_settings(db, user.id, payload.settings)
        event = _user_event(user)
        await db.commit()
    await webhook("/ingest/executors", event)
    return {"user_id": payload.user_id, "settings": payload.settings}


@app.put("/api/user-settings/{user_id}")
async def update_user_settings(user_id: int, payload: UserSettingsInput) -> dict[str, Any]:
    if payload.user_id != user_id:
        raise HTTPException(422, "path user id does not match body user_id")
    async with Session() as db:
        user = await db.get(User, user_id)
        if user is None:
            raise HTTPException(404, "user not found")
        user.settings_json = payload.settings
        user.source_updated_at = datetime.now(timezone.utc)
        await store_user_settings(db, user.id, payload.settings)
        event = _user_event(user)
        await db.commit()
    await webhook("/ingest/executors", event)
    return {"user_id": user_id, "settings": payload.settings}


@app.delete("/api/user-settings/{user_id}")
async def delete_user_settings(user_id: int) -> dict[str, bool]:
    async with Session() as db:
        user = await db.get(User, user_id)
        if user is None:
            raise HTTPException(404, "user not found")
        row = await db.scalar(select(UserSetting).where(UserSetting.user_id == user_id))
        if row is not None:
            await db.delete(row)
        user.settings_json = {}
        user.source_updated_at = datetime.now(timezone.utc)
        event = _user_event(user)
        await db.commit()
    await webhook("/ingest/executors", event)
    return {"ok": True}


def _user_event(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "middle_name": user.middle_name,
        "status": user.status,
        "settings": user.settings_json,
        "source_updated_at": user.source_updated_at,
    }


@app.put("/api/users/{user_id}")
async def update_user(user_id: int, payload: UserInput) -> dict[str, Any]:
    if payload.id != user_id:
        raise HTTPException(422, "path id does not match body id")
    return await create_user(payload)


@app.delete("/api/users/{user_id}")
async def deactivate_user(user_id: int) -> dict[str, bool]:
    async with Session() as db:
        user = await db.get(User, user_id)
        if user is None:
            raise HTTPException(404, "user not found")
        user.status = "inactive"
        user.source_updated_at = datetime.now(timezone.utc)
        await db.commit()
        event = {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "middle_name": user.middle_name,
            "status": user.status,
            "settings": user.settings_json,
            "source_updated_at": user.source_updated_at,
        }
    await webhook("/ingest/executors", event)
    return {"ok": True}


@app.post("/api/orders")
async def create_order(payload: OrderInput) -> dict[str, Any]:
    async with Session() as db:
        order = await db.get(AISOrder, payload.id)
        if order is not None and order.source_updated_at > payload.source_updated_at:
            raise HTTPException(409, "stale order update")
        if order is None:
            order = AISOrder(
                **payload.model_dump(exclude={"attributes"}), attributes_json=payload.attributes
            )
            db.add(order)
        else:
            old_status = order.status
            for key, value in payload.model_dump().items():
                if key == "attributes":
                    order.attributes_json = value
                elif (
                    key == "status"
                    and order.executor_id is not None
                    and value in {"accept", "reject"}
                ):
                    order.status = value
                else:
                    setattr(order, key, value)
            if old_status in {"accept", "reject"} and payload.status in {"processed", "await"}:
                order.executor_id = None
        await db.commit()
    event = {**payload.model_dump(), "sum": payload.amount, "attributes": payload.attributes}
    await webhook("/ingest/orders", event)
    return event


@app.get("/api/orders")
async def list_orders() -> list[dict[str, Any]]:
    async with Session() as db:
        rows = (await db.scalars(select(AISOrder).order_by(AISOrder.id.desc()))).all()
        return [
            {
                "id": r.id,
                "parent_id": r.parent_id,
                "status": r.status,
                "amount": r.amount,
                "weight": float(r.weight),
                "executor_id": r.executor_id,
                "assignment_state": "assigned" if r.executor_id is not None else "pending",
                "attributes": {
                    "order_type": r.order_type,
                    "subject": r.subject,
                    "vip": r.vip,
                },
                "received_at": r.source_updated_at,
            }
            for r in rows
        ]


@app.put("/api/orders/{order_id}")
async def update_order(order_id: int, payload: OrderInput) -> dict[str, Any]:
    if payload.id != order_id:
        raise HTTPException(422, "path id does not match body id")
    return await create_order(payload)


@app.patch("/api/orders/{order_id}/status")
async def update_order_status(order_id: int, body: OrderStatusInput) -> dict[str, Any]:
    async with Session() as db:
        row = await db.get(AISOrder, order_id)
        if row is None:
            raise HTTPException(404, "order not found")
        payload = OrderInput(
            id=row.id,
            parent_id=row.parent_id,
            user_id=row.user_id,
            amount=row.amount,
            weight=float(row.weight),
            client_msp=row.client_msp,
            executor_msp=row.executor_msp,
            order_type=row.order_type,
            subject=row.subject,
            vip=row.vip,
            text=row.text,
            status=body.status,
            attributes=row.attributes_json,
        )
    return await create_order(payload)


@app.delete("/api/orders/{order_id}")
async def close_order(order_id: int) -> dict[str, bool]:
    async with Session() as db:
        row = await db.get(AISOrder, order_id)
        if row is None:
            raise HTTPException(404, "order not found")
        row.status = "reject"
        row.source_updated_at = datetime.now(timezone.utc)
        row.executor_id = None
        payload: dict[str, Any] = {
            "id": row.id,
            "parent_id": row.parent_id,
            "status": row.status,
            "sum": row.amount,
            "client_msp": row.client_msp,
            "executor_msp": row.executor_msp,
            "order_type": row.order_type,
            "subject": row.subject,
            "vip": row.vip,
            "text": row.text,
            "weight": float(row.weight),
            "attributes": row.attributes_json,
            "source_updated_at": row.source_updated_at.isoformat(),
        }
        await db.commit()
    await webhook("/ingest/orders", payload)
    return {"ok": True}


class OrderSimulation(BaseModel):
    rate_per_hour: int = Field(default=4000, ge=1, le=1_000_000)
    burst: dict[str, float] = Field(
        default_factory=lambda: {"rps": 50.0, "duration_s": 60.0, "every_s": 300.0}
    )
    threads: int = Field(default=4, ge=1, le=64)
    parent_ratio: float = Field(default=0.1, ge=0, le=1)


class StatusSimulation(BaseModel):
    threads: int = Field(default=4, ge=1, le=64)
    close_after_s: list[int] = Field(default_factory=lambda: [10, 60])
    review_ratio: float = Field(default=0.2, ge=0, le=1)


class ChaosSimulation(BaseModel):
    deactivate_ratio: float = Field(default=0.15, ge=0, le=1)
    every_s: float = Field(default=10, ge=1, le=86400)


@app.post("/sim/orders/start")
async def start_order_simulation(config: OrderSimulation) -> dict[str, str]:
    config.threads = max(1, min(config.threads, 64))
    config.rate_per_hour = max(1, min(config.rate_per_hour, 1_000_000))
    config.parent_ratio = max(0, min(config.parent_ratio, 1))
    config.burst["rps"] = max(0.01, min(config.burst.get("rps", 50), 1000))
    config.burst["duration_s"] = max(0, config.burst.get("duration_s", 60))
    config.burst["every_s"] = max(1, config.burst.get("every_s", 300))

    async def generate(_worker_index: int) -> None:
        while True:
            now = asyncio.get_running_loop().time()
            cycle = float(config.burst.get("every_s", 300))
            burst_duration = float(config.burst.get("duration_s", 60))
            is_burst = cycle > 0 and now % cycle < burst_duration
            rps = float(config.burst.get("rps", 50)) if is_burst else config.rate_per_hour / 3600
            interval = max(0.001, config.threads / max(rps, 0.01))
            try:
                async with Session() as db:
                    parents = list(
                        (
                            await db.scalars(
                                select(AISOrder.id)
                                .where(AISOrder.executor_id.is_not(None))
                                .limit(1000)
                            )
                        ).all()
                    )
            except Exception:
                await asyncio.sleep(1)
                continue
            parent_id = (
                random.choice(parents)
                if parents and random.random() < config.parent_ratio
                else None
            )
            payload = OrderInput(
                id=next(sim_order_ids),
                parent_id=parent_id,
                amount=random.randint(5000, 900000),
                client_msp=random.choice(["yes", "no"]),
                executor_msp=random.choice(["yes", "no"]),
                order_type=random.choice(["ORDER_1", "ORDER_2", "ORDER_3"]),
                subject=random.choice(["subject-a", "subject-b", "subject-c"]),
                vip=random.random() < 0.1,
                text="Симуляционная заявка",
                status="processed",
            )
            try:
                await create_order(payload)
                simulation_counts["orders"] += 1
            except Exception:
                pass
            await asyncio.sleep(interval)

    async def runner() -> None:
        await asyncio.gather(*(generate(index) for index in range(config.threads)))

    global sim_order_ids
    async with order_simulation_start_lock:
        if "orders" in simulation_tasks and not simulation_tasks["orders"].done():
            raise HTTPException(409, "order simulator already running")
        async with Session() as db:
            last_order_id = await db.scalar(select(func.max(AISOrder.id)))
        sim_order_ids = itertools.count(next_sim_order_id_start(last_order_id))
        simulation_tasks["orders"] = asyncio.create_task(runner())
    return {"status": "started"}


@app.post("/sim/statuses/start")
async def start_status_simulation(config: StatusSimulation) -> dict[str, str]:
    if "statuses" in simulation_tasks and not simulation_tasks["statuses"].done():
        raise HTTPException(409, "status simulator already running")
    config.threads = max(1, min(config.threads, 64))
    config.review_ratio = max(0, min(config.review_ratio, 1))
    config.close_after_s = [max(1, min(value, 86400)) for value in config.close_after_s[:2]] or [
        10,
        60,
    ]

    async def run() -> None:
        while True:
            async with Session() as db:
                rows = list(
                    (
                        await db.scalars(
                            select(AISOrder)
                            .where(
                                AISOrder.executor_id.is_not(None), AISOrder.status == "processed"
                            )
                            .limit(max(1, config.threads * 8))
                        )
                    ).all()
                )
                payloads = [
                    OrderInput(
                        id=row.id,
                        parent_id=row.parent_id,
                        user_id=row.user_id,
                        amount=row.amount,
                        client_msp=row.client_msp,
                        executor_msp=row.executor_msp,
                        order_type=row.order_type,
                        subject=row.subject,
                        vip=row.vip,
                        text=row.text,
                        status="await"
                        if row.parent_id and random.random() < config.review_ratio
                        else random.choice(["accept", "reject"]),
                    )
                    for row in rows
                ]
            for payload in payloads:
                try:
                    await create_order(payload)
                    simulation_counts["status_changes"] += 1
                except Exception:
                    continue
            await asyncio.sleep(random.randint(*sorted(config.close_after_s)))

    simulation_tasks["statuses"] = asyncio.create_task(run())
    return {"status": "started"}


@app.post("/sim/executors/chaos")
async def start_chaos(config: ChaosSimulation) -> dict[str, str]:
    if "chaos" in simulation_tasks and not simulation_tasks["chaos"].done():
        raise HTTPException(409, "executor chaos already running")
    config.deactivate_ratio = max(0, min(config.deactivate_ratio, 1))
    config.every_s = max(1, min(config.every_s, 86400))

    async def run() -> None:
        while True:
            async with Session() as db:
                users = list((await db.scalars(select(User))).all())
                random.shuffle(users)
                selected = users[: max(1, int(len(users) * config.deactivate_ratio))]
                changed = [
                    UserInput(
                        id=u.id,
                        first_name=u.first_name,
                        last_name=u.last_name,
                        middle_name=u.middle_name,
                        status="inactive" if u.status == "active" else "active",
                        settings={**u.settings_json, "qualification": random.randint(1, 5)},
                    )
                    for u in selected
                ]
            for payload in changed:
                try:
                    await create_user(payload)
                    simulation_counts["chaos_changes"] += 1
                except Exception:
                    continue
            await asyncio.sleep(max(1, config.every_s))

    simulation_tasks["chaos"] = asyncio.create_task(run())
    return {"status": "started"}


@app.post("/sim/stop")
async def stop_simulation() -> dict[str, int]:
    for task in simulation_tasks.values():
        task.cancel()
    if simulation_tasks:
        await asyncio.gather(*simulation_tasks.values(), return_exceptions=True)
    simulation_tasks.clear()
    return simulation_counts.copy()


@app.get("/sim/status")
async def simulation_status() -> dict[str, Any]:
    return {
        "running": [name for name, task in simulation_tasks.items() if not task.done()],
        **simulation_counts,
    }


@app.post("/api/assignments")
async def assignment(
    payload: dict[str, Any],
    request: Request,
) -> dict[str, bool]:
    idempotency_key = request.headers.get("Idempotency-Key")
    created = False
    async with Session() as db:
        key = idempotency_key or f"{payload['order_id']}:{payload['executor_id']}"
        row = await db.get(AISOrder, int(payload["order_id"]))
        if row is None:
            raise HTTPException(404, "order not found")
        row.executor_id = int(payload["executor_id"])
        receipt = await db.get(AISAssignment, (row.id, key))
        if receipt is not None and receipt.executor_id != int(payload["executor_id"]):
            raise HTTPException(409, "idempotency key was already used for another executor")
        if receipt is None:
            db.add(AISAssignment(order_id=row.id, executor_id=row.executor_id, idempotency_key=key))
            created = True
        await db.commit()
        receipt_payload = {
            **payload,
            "order_id": row.id,
            "executor_id": row.executor_id,
            "idempotency_key": key,
        }

    async def confirm() -> None:
        for attempt in range(8):
            await asyncio.sleep(random.uniform(2, 10) if attempt == 0 else min(2**attempt, 60))
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.post(
                        settings.balancer_url + "/ingest/assignment-confirmed",
                        json=receipt_payload,
                        headers={"X-Webhook-Secret": settings.webhook_secret},
                    )
                    response.raise_for_status()
                return
            except httpx.HTTPError:
                continue

    if created:
        asyncio.create_task(confirm())
    return {"ok": True}
