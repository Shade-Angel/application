"""Idempotent local demo seed for lookup data and the 60 AIS executors."""

import asyncio
import random

import httpx
from sqlalchemy import select

from app.ais import AISBase, User, store_user_settings
from app.ais import Session as AISSession
from app.ais import engine as ais_engine
from app.config import settings
from app.db import Session, engine
from app.models import (
    Base,
    Dictionary,
    DictionaryItem,
    ParameterDefinition,
    StrategySettings,
)

PARAMETERS = [
    ("order", "sum", "Сумма", "number"),
    ("order", "client_msp", "МСП клиента", "string"),
    ("order", "executor_msp", "МСП исполнителя", "string"),
    ("order", "order_type", "Тип заявки", "enum"),
    ("order", "subject", "Предмет", "enum"),
    ("order", "vip", "VIP", "boolean"),
    ("executor", "min_accept_sum", "Минимальная сумма принятия", "number"),
    ("executor", "max_accept_sum", "Максимальная сумма принятия", "number"),
    ("executor", "min_reject_sum", "Минимальная сумма отказа", "number"),
    ("executor", "max_reject_sum", "Максимальная сумма отказа", "number"),
    ("executor", "client_msp", "МСП клиента исполнителя", "string"),
    ("executor", "executor_msp", "МСП исполнителя", "string"),
    ("executor", "order_type", "Тип заявки исполнителя", "enum"),
    ("executor", "subject", "Предмет исполнителя", "enum"),
    ("executor", "vip", "Может брать VIP", "boolean"),
    ("executor", "max_daily_limit", "Дневной лимит", "number"),
    ("executor", "qualification", "Квалификация", "number"),
]


async def seed() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with ais_engine.begin() as connection:
        await connection.run_sync(AISBase.metadata.create_all)
    async with Session() as db, AISSession() as ais:
        for entity, key, label, data_type in PARAMETERS:
            exists = await db.scalar(
                select(ParameterDefinition.id).where(
                    ParameterDefinition.entity == entity, ParameterDefinition.key == key
                )
            )
            if exists is None:
                db.add(
                    ParameterDefinition(
                        entity=entity, key=key, label=label, data_type=data_type, is_system=True
                    )
                )
        for code, label, values in (
            ("order_type", "Тип заявки", ["ORDER_1", "ORDER_2", "ORDER_3"]),
            ("subject", "Предмет", ["subject-a", "subject-b", "subject-c"]),
        ):
            dictionary = await db.scalar(select(Dictionary).where(Dictionary.code == code))
            if dictionary is None:
                dictionary = Dictionary(code=code, label=label)
                db.add(dictionary)
                await db.flush()
            existing_values = set(
                (
                    await db.scalars(
                        select(DictionaryItem.value).where(
                            DictionaryItem.dictionary_id == dictionary.id
                        )
                    )
                ).all()
            )
            for value in values:
                if value not in existing_values:
                    db.add(DictionaryItem(dictionary_id=dictionary.id, value=value, label=value))
            for entity in ("order", "executor"):
                parameter_key = "order_type" if code == "order_type" else "subject"
                parameter = await db.scalar(
                    select(ParameterDefinition).where(
                        ParameterDefinition.entity == entity,
                        ParameterDefinition.key == parameter_key,
                    )
                )
                if parameter is not None:
                    parameter.dictionary_id = dictionary.id
        if await db.get(StrategySettings, 1) is None:
            db.add(StrategySettings(id=1))
        rng = random.Random(2026)
        for user_id in range(1, 61):
            user = await ais.get(User, user_id)
            if user is None:
                settings = {
                    "min_accept_sum": rng.choice([None, 10000, 50000]),
                    "max_accept_sum": rng.choice([100000, 500000, 1000000]),
                    "min_reject_sum": None,
                    "max_reject_sum": None,
                    "client_msp": rng.choice(["yes", "no"]),
                    "executor_msp": rng.choice(["yes", "no"]),
                    "order_type": rng.choice(["ORDER_1", "ORDER_2", "ORDER_3"]),
                    "subject": rng.choice(["subject-a", "subject-b", "subject-c"]),
                    "vip": user_id % 10 == 0,
                    "max_daily_limit": None if user_id % 5 == 0 else rng.randint(20, 60),
                    "qualification": rng.randint(1, 5),
                }
                user = User(
                    id=user_id,
                    first_name=f"Исполнитель {user_id}",
                    last_name="Демо",
                    middle_name=None,
                    status="inactive" if user_id % 13 == 0 else "active",
                    settings_json=settings,
                )
                ais.add(user)
                await ais.flush()
            else:
                settings = user.settings_json
            if user.status == "active" and user_id % 13 == 0:
                user.status = "inactive"
            if "qualification" not in settings:
                settings["qualification"] = rng.randint(1, 5)
                user.settings_json = settings
            await store_user_settings(ais, user_id, settings)
        await ais.commit()
        await db.commit()


async def sync_executors() -> None:
    async with AISSession() as ais:
        users = list((await ais.scalars(select(User).order_by(User.id))).all())
    async with httpx.AsyncClient(timeout=10) as client:
        for user in users:
            event = {
                "id": user.id,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "middle_name": user.middle_name,
                "status": user.status,
                "settings": user.settings_json,
                # httpx's json= encoder uses the stdlib JSON encoder, which
                # cannot serialize datetime objects. The ingest endpoint
                # accepts ISO-8601 timestamps, as produced by Pydantic.
                "source_updated_at": user.source_updated_at.isoformat(),
            }
            response = await client.post(
                settings.balancer_url + "/ingest/executors",
                json=event,
                headers={
                    "X-Event-Id": f"seed-executor-{user.id}-{user.source_updated_at.isoformat()}",
                    "X-Webhook-Secret": settings.webhook_secret,
                },
            )
            response.raise_for_status()


if __name__ == "__main__":
    import sys

    asyncio.run(sync_executors() if sys.argv[1:] == ["--sync"] else seed())
