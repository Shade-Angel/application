"""Transactional outbox dispatcher with exponential retry and dead-letter handling."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.config import settings
from app.db import Session
from app.models import Order, Outbox

logging.basicConfig(level=logging.INFO)


async def dispatch_once(client: httpx.AsyncClient) -> None:
    async with Session() as db:
        timeout_before = datetime.now(timezone.utc) - timedelta(seconds=settings.confirm_timeout)
        timed_out = list(
            (
                await db.scalars(
                    select(Outbox)
                    .where(Outbox.status == "sent", Outbox.sent_at < timeout_before)
                    .limit(64)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for row in timed_out:
            row.status = "dead" if row.attempts >= settings.max_attempts else "retry"
            row.retry_at = datetime.now(timezone.utc) + timedelta(
                seconds=min(2 ** max(row.attempts - 1, 0), 300)
            )
        outbox_rows = list(
            (
                await db.scalars(
                    select(Outbox)
                    .where(
                        Outbox.status.in_(["new", "retry"]),
                        (Outbox.retry_at.is_(None))
                        | (Outbox.retry_at <= datetime.now(timezone.utc)),
                    )
                    .order_by(Outbox.id)
                    .limit(64)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        row_ids = [outbox_row.id for outbox_row in outbox_rows]
        await db.commit()
    for row_id in row_ids:
        async with Session() as db:
            outbox_row = await db.scalar(
                select(Outbox)
                .where(Outbox.id == row_id, Outbox.status.in_(["new", "retry"]))
                .with_for_update()
            )
            if outbox_row is None:
                continue
            row = outbox_row
            try:
                row.attempts += 1
                response = await client.post(
                    f"{settings.ais_url}/api/assignments",
                    json={"order_id": row.order_id, "executor_id": row.executor_id},
                    headers={"Idempotency-Key": row.idempotency_key},
                )
                response.raise_for_status()
                row.status = "sent"
                row.sent_at = datetime.now(timezone.utc)
                order = await db.get(Order, row.order_id)
                if order is not None:
                    order.assignment_state = "sent"
            except httpx.HTTPError as exc:
                row.last_error = str(exc)[:2000]
                row.retry_at = datetime.now(timezone.utc) + timedelta(
                    seconds=min(2 ** max(row.attempts - 1, 0), 300)
                )
                logging.warning(
                    "AIS dispatch failed", extra={"outbox_id": row.id, "error": str(exc)}
                )
                if row.attempts >= settings.max_attempts:
                    row.status = "dead"
                    row.retry_at = None
            await db.commit()


async def run() -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                await dispatch_once(client)
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.exception("Outbox dispatch cycle failed")
                await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(run())
