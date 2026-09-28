from decimal import Decimal
from types import SimpleNamespace

from app.matching import executor_score, select_candidate


def test_parent_executor_precedes_load_score_and_daily_cap() -> None:
    parent_executor = SimpleNamespace(
        id=5,
        open_weight=Decimal(99),
        day_weight=Decimal(99),
        capacity=Decimal(1),
        daily_limit=1,
        day_count=1,
    )
    least_loaded = SimpleNamespace(
        id=8,
        open_weight=Decimal(0),
        day_weight=Decimal(0),
        capacity=Decimal(1),
        daily_limit=None,
        day_count=0,
    )
    assert (
        select_candidate(
            [least_loaded, parent_executor],
            parent_executor.id,
            lambda executor: executor_score(executor, alpha=1, beta=1, gamma=0),
            {least_loaded.id},
        )
        is parent_executor
    )


def test_lower_open_and_daily_weight_has_lower_score() -> None:
    light = SimpleNamespace(
        open_weight=Decimal(1), day_weight=Decimal(2), capacity=Decimal(2), daily_limit=10
    )
    busy = SimpleNamespace(
        open_weight=Decimal(5), day_weight=Decimal(8), capacity=Decimal(1), daily_limit=10
    )
    assert executor_score(light, alpha=1, beta=0.3, gamma=0) < executor_score(
        busy, alpha=1, beta=0.3, gamma=0
    )


def test_capacity_and_rule_bonus_lower_score() -> None:
    standard = SimpleNamespace(
        open_weight=Decimal(10), day_weight=Decimal(10), capacity=Decimal(1), daily_limit=10
    )
    capable = SimpleNamespace(
        open_weight=Decimal(10), day_weight=Decimal(10), capacity=Decimal(2), daily_limit=10
    )
    assert executor_score(capable, alpha=1, beta=0, gamma=0) < executor_score(
        standard, alpha=1, beta=0, gamma=0
    )
    assert executor_score(standard, alpha=1, beta=0, gamma=2, bonus=1) < executor_score(
        standard, alpha=1, beta=0, gamma=0
    )
