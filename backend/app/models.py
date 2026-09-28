from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(schema="balancer")


class Executor(Base):
    __tablename__ = "executors"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(512), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    capacity: Mapped[Decimal] = mapped_column(Numeric(8, 3), default=Decimal(1))
    daily_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open_count: Mapped[int] = mapped_column(Integer, default=0)
    open_weight: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal(0))
    day_date: Mapped[date] = mapped_column(Date, server_default=func.current_date())
    day_count: Mapped[int] = mapped_column(Integer, default=0)
    day_weight: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal(0))
    last_assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(BigInteger, default=0)
    source_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_state_received", "assignment_state", "received_at"),
        Index("ix_orders_executor_slot", "executor_id", "holds_slot"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    weight: Mapped[Decimal] = mapped_column(Numeric(8, 3), default=Decimal(1))
    executor_id: Mapped[int | None] = mapped_column(ForeignKey("executors.id"), nullable=True)
    assignment_state: Mapped[str] = mapped_column(String(32), default="pending")
    rejection_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    holds_slot: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ParameterDefinition(Base):
    __tablename__ = "parameter_definitions"
    __table_args__ = (UniqueConstraint("entity", "key", name="uq_parameter_entity_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity: Mapped[str] = mapped_column(String(16))
    key: Mapped[str] = mapped_column(String(255))
    label: Mapped[str] = mapped_column(String(255))
    data_type: Mapped[str] = mapped_column(String(32))
    dictionary_id: Mapped[int | None] = mapped_column(ForeignKey("dictionaries.id"), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)


class Rule(Base):
    __tablename__ = "rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32))
    condition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    effect: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    null_policy: Mapped[str] = mapped_column(String(16), default="pass")


class ProcessedEvent(Base):
    __tablename__ = "processed_events"
    __table_args__ = (Index("ix_processed_events_received", "received_at"),)
    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Dictionary(Base):
    __tablename__ = "dictionaries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(128), unique=True)
    label: Mapped[str] = mapped_column(String(255))


class DictionaryItem(Base):
    __tablename__ = "dictionary_items"
    __table_args__ = (UniqueConstraint("dictionary_id", "value"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dictionary_id: Mapped[int] = mapped_column(ForeignKey("dictionaries.id", ondelete="CASCADE"))
    value: Mapped[str] = mapped_column(String(255))
    label: Mapped[str] = mapped_column(String(255))


class StrategySettings(Base):
    __tablename__ = "strategy_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    mode: Mapped[str] = mapped_column(String(32), default="open_load")
    alpha: Mapped[Decimal] = mapped_column(Numeric, default=Decimal(1))
    beta: Mapped[Decimal] = mapped_column(Numeric, default=Decimal("0.3"))
    gamma: Mapped[Decimal] = mapped_column(Numeric, default=Decimal(1))


class AssignmentLog(Base):
    __tablename__ = "assignment_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger)
    executor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reason: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExecutorDailyUsage(Base):
    __tablename__ = "executor_daily_usage"
    __table_args__ = (UniqueConstraint("executor_id", "day_date"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    executor_id: Mapped[int] = mapped_column(BigInteger, index=True)
    day_date: Mapped[date] = mapped_column(Date, index=True)
    assigned_count: Mapped[int] = mapped_column(Integer, default=0)
    assigned_weight: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal(0))


class CandidateDecision(Base):
    __tablename__ = "candidate_decisions"
    __table_args__ = (
        Index("ix_candidate_decisions_order_id", "order_id"),
        Index("ix_candidate_decisions_executor", "executor_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger)
    executor_id: Mapped[int] = mapped_column(BigInteger)
    passed: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(String(255))
    score: Mapped[Decimal | None] = mapped_column(Numeric(14, 6), nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = (Index("ix_outbox_status_id", "status", "id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger)
    executor_id: Mapped[int] = mapped_column(BigInteger)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="new")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StreamEvent(Base):
    __tablename__ = "stream_events"
    __table_args__ = (Index("ix_stream_events_unpublished", "published_at", "id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
