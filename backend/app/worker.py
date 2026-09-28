"""Redis Streams consumer for order matching and atomic reservation."""

import asyncio
import logging
import os
import socket
import uuid

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.config import settings
from app.db import Session
from app.matching import assign
from app.metrics import reservation_conflicts
from app.models import Order

logging.basicConfig(level=logging.INFO)


async def run() -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)

    async def process(entries: list[tuple[str, dict[str, str]]]) -> None:
        for message_id, fields in entries:
            try:
                order_id = int(fields["order_id"])
                async with Session() as db:
                    order = await db.scalar(
                        select(Order).where(Order.id == order_id).with_for_update()
                    )
                    if order is not None and order.assignment_state == "pending":
                        await assign(db, order)
                        await db.commit()
                await redis.xack("bal.orders", "workers", message_id)
            except (KeyError, ValueError):
                await redis.xadd("bal.orders.dlq", {"source_id": message_id, **fields})
                await redis.xack("bal.orders", "workers", message_id)
            except DBAPIError as exc:
                if (
                    "deadlock detected" in str(exc).lower()
                    or "could not serialize" in str(exc).lower()
                ):
                    reservation_conflicts.inc()
                logging.exception("Order event failed", extra={"stream_id": message_id})
            except Exception:
                logging.exception("Order event failed", extra={"stream_id": message_id})

    async def consume(consumer: str) -> None:
        while True:
            try:
                _, reclaimed, _ = await redis.xautoclaim(
                    "bal.orders",
                    "workers",
                    consumer,
                    min_idle_time=30_000,
                    start_id="0-0",
                    count=32,
                )
                if reclaimed:
                    await process(reclaimed)
                messages = await redis.xreadgroup(
                    "workers",
                    consumer,
                    {"bal.orders": ">"},
                    count=32,
                    block=1000,
                )
                for _, entries in messages:
                    await process(entries)
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.exception(
                    "Redis stream consumer iteration failed", extra={"consumer": consumer}
                )
                await asyncio.sleep(1)

    try:
        try:
            await redis.xgroup_create("bal.orders", "workers", id="0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        instance = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        consumers = (
            consume(f"{instance}-{index}") for index in range(max(1, settings.worker_concurrency))
        )
        await asyncio.gather(*consumers)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(run())
