"""A ``ToolContext`` for evals: fake clinic, dry-run submitter, temp call log.

Every case gets a fresh context, exactly like every socket gets a fresh
``CallSession`` in production. Nothing is shared between cases.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from vortex.clinic.client import ClinicApi, FakeClinicClient
from vortex.contract import MADRID, ToolContext
from vortex.line.submit import DryRunSubmitClient
from vortex.observability.calllog import CallLog

DEFAULT_NOW = "2026-09-18T09:00:00+02:00"  # Friday. Public cases anchor to 09:00 Madrid.


def parse_now(value: str | None) -> datetime:
    """An ISO timestamp with an offset, resolved to Europe/Madrid."""
    raw = value or DEFAULT_NOW
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MADRID)
    return dt.astimezone(MADRID)


def make_context(
    *,
    call_id: str,
    now: str | None = None,
    from_number: str | None = None,
    log_dir: Path,
    clinic: ClinicApi | None = None,
) -> ToolContext:
    log_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in call_id)
    return ToolContext(
        call_id=call_id,
        now=parse_now(now),
        from_number=from_number,
        clinic=clinic or FakeClinicClient(),
        log=CallLog(call_id, log_dir / f"{safe}.jsonl"),
        submitter=DryRunSubmitClient(),
    )


def submitted_actions(ctx: ToolContext) -> list[dict[str, Any]]:
    """What the call would have POSTed, in order: ``{"kind": ..., **payload}``."""
    submitter = ctx.submitter
    out: list[dict[str, Any]] = []
    for route, payload in getattr(submitter, "sent", []):
        kind = route.rsplit("/", 1)[-1]
        body = {k: v for k, v in payload.items() if k != "call_id"}
        out.append({"kind": kind, **body})
    return out
