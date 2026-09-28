from datetime import datetime, timezone
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.dsl import compile_condition, interpret_condition


@pytest.mark.parametrize(
    "op,actual,expected,want",
    [
        ("eq", 2, 2, True),
        ("ne", 2, 3, True),
        ("gt", 3, 2, True),
        ("gte", 2, 2, True),
        ("lt", 1, 2, True),
        ("lte", 2, 2, True),
        ("in", "x", ["x", "y"], True),
        ("contains", ["x", "y"], "y", True),
        ("exists", 0, True, True),
    ],
)
def test_operators(op: str, actual: Any, expected: Any, want: bool) -> None:
    assert (
        compile_condition({"field": "executor.value", "op": op, "value": expected})(
            {"executor": {"value": actual}}
        )
        is want
    )


def test_nested_groups_and_missing_field() -> None:
    rule = {
        "all": [
            {"field": "order.sum", "op": "gte", "value": 10},
            {"not": {"field": "executor.vip", "op": "eq", "value": False}},
        ]
    }
    assert compile_condition(rule)({"order": {"sum": 12}, "executor": {"vip": True}})
    assert not compile_condition({"field": "executor.vip", "op": "eq", "value": True})(
        {"executor": {}}
    )


@given(st.integers(), st.integers())
def test_interpreter_comparison_matches_native(left: int, right: int) -> None:
    assert compile_condition({"field": "v", "op": "gte", "value": right})({"v": left}) == (
        left >= right
    )


def test_unknown_operator_is_rejected() -> None:
    with pytest.raises(ValueError):
        compile_condition({"field": "v", "op": "almost", "value": 1})


@pytest.mark.parametrize(
    "condition,context,want",
    [
        (
            {"field": "order.amount", "op": "between", "value": [10, 20]},
            {"order": {"amount": 15}},
            True,
        ),
        (
            {"field": "executor.types", "op": "contains_all", "value": ["A", "B"]},
            {"executor": {"types": ["A", "B", "C"]}},
            True,
        ),
        (
            {"field": "executor.types", "op": "intersects", "value": ["C"]},
            {"executor": {"types": ["A", "B"]}},
            False,
        ),
        (
            {"field": "order.text", "op": "regex", "value": "^ORD-[0-9]+$"},
            {"order": {"text": "ORD-123"}},
            True,
        ),
        (
            {"field": "order.text", "op": "starts_with", "value": "ORD"},
            {"order": {"text": "ORD-1"}},
            True,
        ),
        (
            {"field": "executor.vip", "op": "implies", "value": False},
            {"executor": {"vip": False}},
            True,
        ),
        ({"field": "order.optional", "op": "is_null"}, {"order": {}}, True),
        ({"field": "order.tags", "op": "is_empty"}, {"order": {"tags": []}}, True),
        (
            {"field": "order.created", "op": "within_last", "value": "PT24H"},
            {"order": {"created": datetime.now(timezone.utc).isoformat()}},
            True,
        ),
        (
            {
                "combinator": "and",
                "rules": [{"left": {"ref": "order.amount"}, "op": "gte", "right": {"value": 10}}],
            },
            {"order": {"amount": 12}},
            True,
        ),
        (
            {"field": "order.amount", "op": "lte", "value": {"field": "executor.max"}},
            {"order": {"amount": 12}, "executor": {"max": 15}},
            True,
        ),
    ],
)
def test_full_dsl_operators_and_reference_ast(
    condition: dict[str, Any], context: dict[str, Any], want: bool
) -> None:
    compiled = compile_condition(condition)
    assert compiled(context) is want
    assert interpret_condition(condition, context) is want


leaf_conditions = st.builds(
    lambda field, op, value: {"field": field, "op": op, "value": value},
    field=st.sampled_from(["order.amount", "executor.capacity"]),
    op=st.sampled_from(["eq", "ne", "gt", "gte", "lt", "lte", "in", "exists"]),
    value=st.one_of(
        st.integers(-10, 10), st.lists(st.integers(-10, 10), max_size=4), st.booleans()
    ),
)
condition_trees = st.recursive(
    leaf_conditions,
    lambda children: st.one_of(
        st.builds(lambda rules: {"all": rules}, st.lists(children, min_size=1, max_size=3)),
        st.builds(lambda rules: {"any": rules}, st.lists(children, min_size=1, max_size=3)),
        st.builds(lambda rule: {"not": rule}, children),
    ),
    max_leaves=12,
)


@given(condition_trees, st.integers(-20, 20), st.integers(-20, 20))
def test_compiled_dsl_matches_reference_interpreter(
    condition: dict[str, Any], amount: int, capacity: int
) -> None:
    context = {"order": {"amount": amount}, "executor": {"capacity": capacity}}
    assert compile_condition(condition)(context) == interpret_condition(condition, context)
