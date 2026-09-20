"""File-backed wall-cancellation store for runs without Supabase.

The wall cancel flow persists hand-cancelled slots so the diary drops them
(``vortex.api._shared.wall_cancelled_keys``). With no Supabase configured the
remote store raises ``database.db.NotConfigured`` and the cancel API would
have to refuse the click. For the offline demo board the cancellation only
needs to stick locally, so the API layer falls back to this JSONL file next
to the other runtime logs. Rows mirror the ``wall_cancellations`` shape.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PATH = Path(__file__).resolve().parent.parent / "logs" / "wall_cancellations.jsonl"


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def insert(
    *,
    provider_id: str,
    site_id: str,
    slot_start: str,
    appointment_id: str | None = None,
    patient_name: str | None = None,
    provider_name: str | None = None,
) -> dict[str, Any]:
    """Append one hand-cancelled slot; returns the stored row."""
    row = {
        "provider_id": provider_id,
        "site_id": site_id,
        "slot_start": slot_start,
        "appointment_id": appointment_id,
        "patient_name": patient_name,
        "provider_name": provider_name,
        "cancelled_at": _now_iso(),
    }
    PATH.parent.mkdir(parents=True, exist_ok=True)
    with PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def list_all() -> list[dict[str, Any]]:
    """Every locally cancelled slot, oldest first."""
    if not PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows
