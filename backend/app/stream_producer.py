"""Publishes transactional stream-outbox rows to Redis Streams."""

import asyncio
import logging
from datetime import datetime, timezone

from redis.asyncio import Redis
from sqlalchemy import select

from app.config import settings
from app.db import Session
from app.models import StreamEvent

logging.basicConfig(level=logging.INFO)


async def run() -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        while True:
            try:
                async with Session() as db:
                    events = list(
                        (
                            await db.scalars(
                                select(StreamEvent)
                                .where(StreamEvent.published_at.is_(None))
                                .order_by(StreamEvent.id)
                                .limit(128)
                                .with_for_update(skip_locked=True)
                            )
                        ).all()
                    )
                    for event in events:
                        await redis.xadd(
                            "bal.orders",
                            {"order_id": str(event.order_id), "event_id": str(event.id)},
                        )
                        event.published_at = datetime.now(timezone.utc)
                    await db.commit()
                await asyncio.sleep(0.1 if events else 0.5)
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.exception("Stream outbox publication failed")
                await asyncio.sleep(1)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(run())
