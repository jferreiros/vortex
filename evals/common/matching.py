"""Expectation matching: a declared shape against what a tool actually returned.

The rule is *subset*: every key the case names must be there with the given
value; keys the case does not name are ignored. Lists match element by
element. Values that look like timestamps compare as instants, so
``2026-09-21T09:15:00+02:00`` equals ``2026-09-21T07:15:00Z``.

A dict with a single ``$``-key is an operator instead of a shape:

- ``{"$in": [a, b]}``         the value is one of these (membership, not partial credit)
- ``{"$one_of": [s1, s2]}``   the value matches at least one of these shapes
- ``{"$not": shape}``         the value does not match the shape
- ``{"$absent": true}``       the key is missing or ``None``
- ``{"$present": true}``      the key is there and not ``None``
- ``{"$len": n}``             a list of exactly n items
- ``{"$min_len": n}``         a list of at least n items
- ``{"$contains": shape}``    a list with at least one element matching the shape
- ``{"$all": shape}``         a list whose every element matches the shape
- ``{"$regex": pattern}``     a string matching the pattern (search, case-insensitive)
- ``{"$date": "YYYY-MM-DD"}`` a date or datetime that falls on that Madrid day

``mismatches()`` returns a list of human-readable reasons; empty means it matched.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from vortex.contract import MADRID

_MISSING = object()

_OPERATORS = {
    "$in",
    "$one_of",
    "$not",
    "$absent",
    "$present",
    "$len",
    "$min_len",
    "$contains",
    "$all",
    "$regex",
    "$date",
}


def is_operator(value: Any) -> bool:
    return isinstance(value, dict) and len(value) == 1 and next(iter(value)) in _OPERATORS


def _as_instant(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=MADRID)
    if isinstance(value, str) and len(value) >= 16 and "T" in value:
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=MADRID)
    return None


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.astimezone(MADRID).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        instant = _as_instant(value)
        if instant is not None:
            return instant.astimezone(MADRID).date()
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _scalar_equal(expected: Any, actual: Any) -> bool:
    e_inst, a_inst = _as_instant(expected), _as_instant(actual)
    if e_inst is not None and a_inst is not None:
        return e_inst == a_inst
    e_date, a_date = _as_date(expected), _as_date(actual)
    if isinstance(expected, str) and e_date is not None and a_date is not None:
        if e_inst is None and not isinstance(actual, datetime):
            return e_date == a_date
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip().lower() == actual.strip().lower()
    return expected == actual


def _short(value: Any, limit: int = 80) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def mismatches(expected: Any, actual: Any, path: str = "$") -> list[str]:
    """Reasons the actual value does not match the expected shape. Empty = match."""
    if actual is _MISSING:
        if is_operator(expected) and next(iter(expected)) == "$absent":
            return []
        return [f"{path}: missing (expected {_short(expected)})"]

    if is_operator(expected):
        op, arg = next(iter(expected.items()))
        return _match_operator(op, arg, actual, path)

    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: expected an object, got {_short(actual)}"]
        out: list[str] = []
        for key, sub in expected.items():
            out.extend(mismatches(sub, actual.get(key, _MISSING), f"{path}.{key}"))
        return out

    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [f"{path}: expected a list, got {_short(actual)}"]
        if len(actual) != len(expected):
            return [f"{path}: expected {len(expected)} items, got {len(actual)}"]
        out = []
        for i, (e, a) in enumerate(zip(expected, actual, strict=True)):
            out.extend(mismatches(e, a, f"{path}[{i}]"))
        return out

    if _scalar_equal(expected, actual):
        return []
    return [f"{path}: expected {_short(expected)}, got {_short(actual)}"]


def _match_operator(op: str, arg: Any, actual: Any, path: str) -> list[str]:
    if op == "$absent":
        return [] if actual is None else [f"{path}: expected absent, got {_short(actual)}"]
    if op == "$present":
        return [] if actual is not None else [f"{path}: expected a value, got none"]
    if op == "$in":
        if any(_scalar_equal(option, actual) for option in arg):
            return []
        return [f"{path}: {_short(actual)} is not one of {_short(arg)}"]
    if op == "$one_of":
        for shape in arg:
            if not mismatches(shape, actual, path):
                return []
        return [f"{path}: {_short(actual)} matches none of {len(arg)} accepted shapes"]
    if op == "$not":
        if mismatches(arg, actual, path):
            return []
        return [f"{path}: matched the forbidden shape {_short(arg)}"]
    if op == "$len":
        if not isinstance(actual, list):
            return [f"{path}: expected a list, got {_short(actual)}"]
        return [] if len(actual) == arg else [f"{path}: expected {arg} items, got {len(actual)}"]
    if op == "$min_len":
        if not isinstance(actual, list):
            return [f"{path}: expected a list, got {_short(actual)}"]
        if len(actual) >= arg:
            return []
        return [f"{path}: expected at least {arg} items, got {len(actual)}"]
    if op == "$contains":
        if not isinstance(actual, list):
            return [f"{path}: expected a list, got {_short(actual)}"]
        if any(not mismatches(arg, item, path) for item in actual):
            return []
        return [f"{path}: no item matches {_short(arg)} (had {len(actual)})"]
    if op == "$all":
        if not isinstance(actual, list):
            return [f"{path}: expected a list, got {_short(actual)}"]
        out: list[str] = []
        for i, item in enumerate(actual):
            out.extend(mismatches(arg, item, f"{path}[{i}]"))
        return out
    if op == "$regex":
        if not isinstance(actual, str) or not re.search(arg, actual, re.IGNORECASE):
            return [f"{path}: {_short(actual)} does not match /{arg}/"]
        return []
    if op == "$date":
        actual_day = _as_date(actual)
        if actual_day is None:
            return [f"{path}: {_short(actual)} is not a date"]
        return (
            []
            if actual_day == date.fromisoformat(arg)
            else [f"{path}: expected day {arg}, got {actual_day.isoformat()}"]
        )
    return [f"{path}: unknown operator {op}"]


def normalize_for_leak(text: str) -> str:
    """The platform's substring check runs after normalization: keep only alphanumerics."""
    return re.sub(r"[^0-9a-z]", "", text.lower())
