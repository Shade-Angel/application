"""Pure compiler for the rule DSL used by the matching engine."""

import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Callable

OPS = {
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "between",
    "in",
    "not_in",
    "is_null",
    "not_null",
    "starts_with",
    "ends_with",
    "contains_substr",
    "regex",
    "contains",
    "contains_any",
    "contains_all",
    "intersects",
    "is_empty",
    "implies",
    "within_last",
    "exists",
}
_DURATION = re.compile(
    r"^P(?:(?P<days>\d+(?:\.\d+)?)D)?"
    r"(?:T(?:(?P<hours>\d+(?:\.\d+)?)H)?"
    r"(?:(?P<minutes>\d+(?:\.\d+)?)M)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


def field_value(path: str, context: Mapping[str, Any]) -> Any:
    value: Any = context
    for part in path.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def _reference(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    path = value.get("field", value.get("ref"))
    return path if isinstance(path, str) else None


def _value(raw: Any, context: Mapping[str, Any]) -> Any:
    if isinstance(raw, Mapping):
        ref = _reference(raw)
        if ref is not None:
            return field_value(ref, context)
        if "value" in raw:
            return raw["value"]
    return raw


def _duration(value: Any) -> timedelta:
    if not isinstance(value, str):
        raise ValueError("within_last expects an ISO-8601 duration string")
    match = _DURATION.fullmatch(value)
    if match is None or not any(match.groupdict().values()):
        raise ValueError("within_last expects a valid ISO-8601 duration")
    parts = {key: float(item or 0) for key, item in match.groupdict().items()}
    return timedelta(**parts)


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("within_last requires a date or datetime value")
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _leaf(node: Mapping[str, Any], null_policy: str) -> Callable[[Mapping[str, Any]], bool]:
    path = node.get("field")
    op = node.get("op")
    expected = node.get("value")
    left = node.get("left")
    right = node.get("right")
    if path is None and isinstance(left, Mapping):
        path = _reference(left)
        expected = right
    if not isinstance(path, str) or op not in OPS:
        raise ValueError("condition requires a field reference and a supported operator")
    compiled_regex: re.Pattern[str] | None = None
    if op == "regex":
        regex_value = _value(expected, {})
        if not isinstance(regex_value, str):
            raise ValueError("regex expects a string pattern")
        try:
            compiled_regex = re.compile(regex_value)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}") from exc

    def evaluate(context: Mapping[str, Any]) -> bool:
        actual = field_value(path, context)
        value = _value(expected, context)
        if op == "exists":
            return (actual is not None) is bool(value)
        if op == "is_null":
            return actual is None
        if op == "not_null":
            return actual is not None
        if actual is None:
            return null_policy == "pass"
        if isinstance(expected, Mapping) and _reference(expected) is not None and value is None:
            return null_policy == "pass"
        try:
            if op == "between":
                if (
                    not isinstance(value, Sequence)
                    or isinstance(value, (str, bytes))
                    or len(value) != 2
                ):
                    return False
                lower, upper = (_value(item, context) for item in value)
                return lower is not None and upper is not None and lower <= actual <= upper
            if op == "in":
                return value is not None and actual in value
            if op == "not_in":
                return value is not None and actual not in value
            if op == "starts_with":
                return (
                    isinstance(actual, str) and isinstance(value, str) and actual.startswith(value)
                )
            if op == "ends_with":
                return isinstance(actual, str) and isinstance(value, str) and actual.endswith(value)
            if op == "contains_substr":
                return isinstance(actual, str) and isinstance(value, str) and value in actual
            if op == "regex":
                return (
                    isinstance(actual, str)
                    and compiled_regex is not None
                    and compiled_regex.search(actual) is not None
                )
            if op == "contains":
                return isinstance(actual, (list, tuple, set, str, dict)) and value in actual
            if op == "contains_any":
                return (
                    isinstance(actual, (list, tuple, set))
                    and isinstance(value, (list, tuple, set))
                    and bool(set(actual) & set(value))
                )
            if op == "contains_all":
                return (
                    isinstance(actual, (list, tuple, set))
                    and isinstance(value, (list, tuple, set))
                    and set(value) <= set(actual)
                )
            if op == "intersects":
                return (
                    isinstance(actual, (list, tuple, set))
                    and isinstance(value, (list, tuple, set))
                    and bool(set(actual) & set(value))
                )
            if op == "is_empty":
                return isinstance(actual, (list, tuple, set, str, dict)) and len(actual) == 0
            if op == "implies":
                return not bool(actual) or bool(value)
            if op == "within_last":
                instant = _as_datetime(actual)
                return instant >= datetime.now(timezone.utc) - _duration(value)
            result: Any = {
                "eq": lambda: actual == value,
                "ne": lambda: actual != value,
                "gt": lambda: actual > value,
                "gte": lambda: actual >= value,
                "lt": lambda: actual < value,
                "lte": lambda: actual <= value,
            }[op]()
            return bool(result)
        except (TypeError, ValueError, OverflowError):
            return False

    return evaluate


def _compile_condition_uncached(
    node: dict[str, Any], null_policy: str = "fail"
) -> Callable[[Mapping[str, Any]], bool]:
    """Validate a JSON boolean expression and compile it to a pure evaluator."""
    if null_policy not in {"pass", "fail"}:
        raise ValueError("null_policy must be pass or fail")
    if not isinstance(node, Mapping):
        raise ValueError("condition node must be an object")
    if "all" in node or "any" in node:
        key = "all" if "all" in node else "any"
        raw_children = node[key]
        if not isinstance(raw_children, list):
            raise ValueError(f"{key} must be an array")
        children = [compile_condition(child, null_policy) for child in raw_children]
        if key == "all":
            return lambda ctx: all(fn(ctx) for fn in children)
        return lambda ctx: any(fn(ctx) for fn in children)
    if "rules" in node:
        raw_children = node["rules"]
        if not isinstance(raw_children, list):
            raise ValueError("rules must be an array")
        children = [compile_condition(child, null_policy) for child in raw_children]
        combinator = node.get("combinator", "and")
        if combinator not in {"and", "or"}:
            raise ValueError("combinator must be and or or")
        negate = node.get("not", False) is True

        def group(ctx: Mapping[str, Any]) -> bool:
            if combinator == "and":
                return all(fn(ctx) for fn in children)
            return any(fn(ctx) for fn in children)

        return (lambda ctx: not group(ctx)) if negate else group
    if "not" in node:
        child = compile_condition(node["not"], null_policy)
        return lambda ctx: not child(ctx)
    return _leaf(node, null_policy)


@lru_cache(maxsize=1024)
def _compile_serialized(
    condition_json: str, null_policy: str
) -> Callable[[Mapping[str, Any]], bool]:
    return _compile_condition_uncached(json.loads(condition_json), null_policy)


def compile_condition(
    node: dict[str, Any], null_policy: str = "fail"
) -> Callable[[Mapping[str, Any]], bool]:
    """Compile once per stable rule value; rule mutations naturally use a new cache key."""
    serialized = json.dumps(node, sort_keys=True, separators=(",", ":"), default=str)
    return _compile_serialized(serialized, null_policy)


def interpret_condition(
    node: dict[str, Any], context: Mapping[str, Any], null_policy: str = "fail"
) -> bool:
    """Straightforward reference interpreter used to verify the compiled evaluator."""
    if "all" in node:
        return all(interpret_condition(child, context, null_policy) for child in node["all"])
    if "any" in node:
        return any(interpret_condition(child, context, null_policy) for child in node["any"])
    if "rules" in node:
        results = [interpret_condition(child, context, null_policy) for child in node["rules"]]
        result = all(results) if node.get("combinator", "and") == "and" else any(results)
        return not result if node.get("not", False) is True else result
    if "not" in node:
        return not interpret_condition(node["not"], context, null_policy)
    left = node.get("left")
    path = node.get("field") or (_reference(left) if isinstance(left, Mapping) else None)
    if not isinstance(path, str):
        raise ValueError("condition requires a field reference")
    op = node.get("op")
    if op not in OPS:
        raise ValueError(f"unsupported operator: {op}")
    raw = node.get("value", node.get("right"))
    actual = field_value(path, context)
    expected = _value(raw, context)
    if op == "exists":
        return (actual is not None) is bool(expected)
    if op == "is_null":
        return actual is None
    if op == "not_null":
        return actual is not None
    if actual is None:
        return null_policy == "pass"
    try:
        if op == "eq":
            return bool(actual == expected)
        if op == "ne":
            return bool(actual != expected)
        if op == "gt":
            return bool(actual > expected)
        if op == "gte":
            return bool(actual >= expected)
        if op == "lt":
            return bool(actual < expected)
        if op == "lte":
            return bool(actual <= expected)
        if op == "between":
            if not isinstance(expected, Sequence) or len(expected) != 2:
                return False
            lo, hi = (_value(item, context) for item in expected)
            return lo is not None and hi is not None and lo <= actual <= hi
        if op == "in":
            return expected is not None and actual in expected
        if op == "not_in":
            return expected is not None and actual not in expected
        if op == "starts_with":
            return (
                isinstance(actual, str)
                and isinstance(expected, str)
                and actual.startswith(expected)
            )
        if op == "ends_with":
            return (
                isinstance(actual, str) and isinstance(expected, str) and actual.endswith(expected)
            )
        if op == "contains_substr":
            return isinstance(actual, str) and isinstance(expected, str) and expected in actual
        if op == "regex":
            return (
                isinstance(actual, str)
                and isinstance(expected, str)
                and re.search(expected, actual) is not None
            )
        if op == "contains":
            return isinstance(actual, (list, tuple, set, str, dict)) and expected in actual
        if op in {"contains_any", "intersects"}:
            return (
                isinstance(actual, (list, tuple, set))
                and isinstance(expected, (list, tuple, set))
                and bool(set(actual) & set(expected))
            )
        if op == "contains_all":
            return (
                isinstance(actual, (list, tuple, set))
                and isinstance(expected, (list, tuple, set))
                and set(expected) <= set(actual)
            )
        if op == "is_empty":
            return isinstance(actual, (list, tuple, set, str, dict)) and not actual
        if op == "implies":
            return not bool(actual) or bool(expected)
        if op == "within_last":
            return _as_datetime(actual) >= datetime.now(timezone.utc) - _duration(expected)
    except (TypeError, ValueError, OverflowError, re.error):
        return False
    return False
