"""Copy the deployed line's real call log into this checkout's own.

The event log is the only record of what really happened on a call, and it
lives on whichever machine answered the socket. A laptop that has never
served a real call therefore has nothing real to read: ``make call`` writes
``CA-fake-*`` practice runs and the mic page writes ``CA-mic-*``, and both
carry stub transcripts. Everything downstream of the log — the board's Home
and Insights pages, and ``database/scripts/backfill_from_logs.py`` — is only
as real as the log it reads, so this script exists to bring the real thing
local.

Reads ``GET {line}/calls?calls=N``, the same endpoint
``vortex/observability/callfeed.py`` already treats as the board's primary
source, and merges the result into ``settings.calls_log_path``.

The merge is by exact event identity, not by position or timestamp: a call
legitimately logs two events of the same kind in the same millisecond, so a
``(call_id, ts, kind)`` key would silently drop one of them. Comparing whole
events means re-running this adds what is new and can never lose or
duplicate what is already there.

Run it:

    uv run python scripts/fetch_prod_calls.py            # the deploy
    uv run python scripts/fetch_prod_calls.py --url http://127.0.0.1:7860
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx

from vortex.observability.view import flatten_grouped
from vortex.settings import get_settings

#: The team's deployed line (deploy/compose.yml, docs/deploy.md). The default
#: is the deploy rather than localhost because pulling a *real* log is this
#: script's whole reason to exist, and a local line has nothing this checkout
#: does not already have. Override with --url.
DEFAULT_LINE_URL = "https://line.167.233.80.47.sslip.io"

#: A 500-call window is several megabytes of events, and the line answers
#: /calls from the same event loop that streams live call audio.
FETCH_TIMEOUT_S = 90.0


def fetch_events(url: str, calls: int, *, timeout: float = FETCH_TIMEOUT_S) -> list[dict[str, Any]]:
    """Every event of the line's most recent ``calls`` calls, oldest first."""
    response = httpx.get(f"{url}/calls", params={"calls": calls}, timeout=timeout)
    response.raise_for_status()
    grouped = response.json().get("calls")
    if not isinstance(grouped, dict):
        raise ValueError(f"{url}/calls answered with no 'calls' object")
    return flatten_grouped(grouped)


def identity(event: dict[str, Any]) -> str:
    """A key equal for two events exactly when they are the same event.

    Canonical (sorted-key) JSON, so an event already in the log matches the
    fetched copy of itself whatever key order either was written in.
    """
    return json.dumps(event, sort_keys=True, ensure_ascii=False)


def existing_identities(path: Path) -> set[str]:
    if not path.exists():
        return set()
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            seen.add(identity(json.loads(line)))
        except json.JSONDecodeError:
            continue
    return seen


def is_practice_call(started: dict[str, Any]) -> bool:
    """Whether a ``call.started`` belongs to something other than a real
    caller, by the same markers ``business_insights.is_real_call`` uses —
    stated over the raw event because this script never builds a ``CallCard``.
    """
    call_id = str(started.get("call_id") or "")
    return (
        call_id.startswith(("probe:", "CA-fake-", "CA-mic-"))
        or started.get("clinic") == "synthetic-data"
        or started.get("voice") == "demo"
    )


def summarise(events: list[dict[str, Any]]) -> tuple[int, int]:
    """(real calls, practice calls) among ``events``."""
    real = practice = 0
    for event in events:
        if event.get("kind") != "call.started":
            continue
        if is_practice_call(event):
            practice += 1
        else:
            real += 1
    return real, practice


def merge(events: list[dict[str, Any]], path: Path) -> list[dict[str, Any]]:
    """The subset of ``events`` the log does not already hold."""
    seen = existing_identities(path)
    fresh: list[dict[str, Any]] = []
    for event in events:
        key = identity(event)
        if key in seen:
            continue
        seen.add(key)
        fresh.append(event)
    return fresh


def append(events: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull the deployed line's real call log.")
    parser.add_argument("--url", default=DEFAULT_LINE_URL, help="line base URL")
    parser.add_argument("--calls", type=int, default=500, help="how many recent calls to ask for")
    parser.add_argument("--out", type=Path, default=None, help="target log (default: settings)")
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = parser.parse_args()

    url = args.url.rstrip("/")
    path = args.out or get_settings().calls_log_path

    events = fetch_events(url, args.calls)
    real, practice = summarise(events)
    print(f"fetched {len(events)} events from {url}: {real} real calls, {practice} practice")

    fresh = merge(events, path)
    new_real, new_practice = summarise(fresh)
    if args.dry_run:
        print(f"dry run: {len(fresh)} new events would be appended to {path}")
        return 0

    append(fresh, path)
    print(
        f"appended {len(fresh)} new events to {path} "
        f"({new_real} real calls, {new_practice} practice); "
        f"{len(events) - len(fresh)} already present"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
