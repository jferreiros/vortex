"""``{{ ... }}`` references inside case files.

A flow step or a scenario can refer to an earlier step's result, to the call
clock, or to an *oracle* the harness computes from the fake clinic. Examples::

    "{{patient.patient.patient_id}}"       a value from the step saved as ``patient``
    "{{slots.slots[0]}}"                    a whole object (the string is the template)
    "{{ctx.today+1}}"                       an ISO date, tomorrow in Madrid
    "{{ctx.now}}"                           the call clock, ISO with offset
    "Hola, {{ctx.today}}"                   embedded: rendered as text

A value that is exactly one reference keeps its type. Anything else renders to
a string. Missing references raise ``TemplateError`` so a typo in a case is a
loud failure, never a silent ``None``.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel

_REF = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_INDEX = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)?((?:\[[0-9]+\])*)$")


class TemplateError(ValueError):
    pass


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _resolve_path(root: dict[str, Any], expr: str) -> Any:
    current: Any = root
    for part in expr.split("."):
        m = _INDEX.match(part)
        if not m:
            raise TemplateError(f"bad path segment {part!r} in {{{{{expr}}}}}")
        name, indexes = m.group(1), m.group(2)
        if name:
            if isinstance(current, dict) and name in current:
                current = current[name]
            elif hasattr(current, name):
                current = getattr(current, name)
            else:
                raise TemplateError(f"{{{{{expr}}}}}: no {name!r} in {type(current).__name__}")
        for idx in re.findall(r"\[([0-9]+)\]", indexes):
            try:
                current = current[int(idx)]
            except (IndexError, KeyError, TypeError) as exc:
                raise TemplateError(f"{{{{{expr}}}}}: index {idx} out of range") from exc
        current = _plain(current)
    return current


def _resolve_ctx(expr: str, now: datetime) -> Any:
    local = now
    if expr == "ctx.now":
        return local.isoformat()
    if expr == "ctx.today":
        return local.date().isoformat()
    m = re.match(r"^ctx\.today([+-])(\d+)$", expr)
    if m:
        delta = int(m.group(2)) * (1 if m.group(1) == "+" else -1)
        return (local.date() + timedelta(days=delta)).isoformat()
    m = re.match(r"^ctx\.now([+-])(\d+)(d|h|m)$", expr)
    if m:
        amount = int(m.group(2)) * (1 if m.group(1) == "+" else -1)
        unit = {"d": "days", "h": "hours", "m": "minutes"}[m.group(3)]
        return (local + timedelta(**{unit: amount})).isoformat()
    raise TemplateError(f"unknown clock reference {{{{{expr}}}}}")


def resolve_ref(expr: str, scope: dict[str, Any], now: datetime) -> Any:
    expr = expr.strip()
    if expr.startswith("ctx."):
        return _resolve_ctx(expr, now)
    return _resolve_path(scope, expr)


def render(value: Any, scope: dict[str, Any], now: datetime) -> Any:
    """Render every template inside ``value`` (dicts, lists, strings)."""
    if isinstance(value, str):
        whole = _REF.fullmatch(value.strip())
        if whole:
            return resolve_ref(whole.group(1), scope, now)
        return _REF.sub(lambda m: str(resolve_ref(m.group(1), scope, now)), value)
    if isinstance(value, dict):
        return {k: render(v, scope, now) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, scope, now) for v in value]
    return value
