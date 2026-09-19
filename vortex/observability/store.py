"""The SQLite query layer behind ``/api/wall/analytics``.

``logs/calls.jsonl`` stays the source of truth. This database is a
rebuildable projection: ``ingest`` tails the log from a byte offset kept
inside the DB itself, so deleting ``calls.db`` and re-ingesting rebuilds
everything, and a crash mid-ingest never duplicates a row — every parsed
line lands in ``events`` under a digest key first, and the derived tables
are only touched for lines that inserted.

What it ingests:

- ``call.started`` / ``call.ended`` / ``call.summary`` — one ``calls`` row
  per ``call_id``: window, duration, masked caller, outcome inputs.
- ``call.intent`` — the caller's classified goal (latest wins).
- ``turn.user`` / ``turn.assistant`` — a ``turns`` row each, with a
  word-count proxy for ``words`` and no timing.
- ``turn.metrics`` — a measured ``turns`` row (``measured=1``) carrying the
  real ``started_ts`` / ``ended_ts`` / ``words`` / ``ttfb_ms``. When a call
  has measured rows the aggregates use them; when it has none they degrade
  to the word-count proxies above, per call.
- ``tool.called`` / ``tool.returned`` / ``tool.failed`` — paired into one
  ``tool_calls`` row per invocation.
- ``submit.sent`` / ``submit.result`` — one ``submissions`` row each.
- ``call.usage`` — the metered counters, stored whole so ``pricing`` can
  re-price the call without any new cost logic.
- ``call.recording`` — where the WAV landed.
- everything else — the ``events`` raw mirror, cheap and complete.

CLI: ``make ingest`` runs ``python -m vortex.observability.store``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from vortex.observability.insights import mask_phone, percentiles
from vortex.observability.pricing import price_call

SCHEMA = """
CREATE TABLE IF NOT EXISTS ingest_state (
    path    TEXT PRIMARY KEY,
    offset  INTEGER NOT NULL DEFAULT 0
);

-- The raw mirror: one row per parsed JSONL line, digest-keyed so re-reading
-- the file (rotation, ``--rebuild`` into a live DB, a retried tail) is a
-- no-op. ``raw`` is the verbatim line.
CREATE TABLE IF NOT EXISTS events (
    event_key   TEXT PRIMARY KEY,
    call_id     TEXT,
    kind        TEXT,
    ts          TEXT,
    raw         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_call ON events (call_id);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events (kind);

CREATE TABLE IF NOT EXISTS calls (
    call_id         TEXT PRIMARY KEY,
    started_ts      TEXT,
    ended_ts        TEXT,
    duration_ms     REAL,
    from_masked     TEXT,
    problem_id      TEXT,
    intent          TEXT,
    ended           INTEGER NOT NULL DEFAULT 0,
    action_kind     TEXT,
    submit_route    TEXT,
    submit_status   TEXT,
    reason          TEXT,
    recording_path  TEXT,
    recording_ms    REAL,
    recording_bytes INTEGER,
    events          INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_calls_started ON calls (started_ts);

CREATE TABLE IF NOT EXISTS turns (
    event_key   TEXT PRIMARY KEY,
    call_id     TEXT NOT NULL,
    speaker     TEXT NOT NULL,
    text        TEXT,
    words       INTEGER NOT NULL DEFAULT 0,
    started_ts  TEXT,
    ended_ts    TEXT,
    ttfb_ms     REAL,
    measured    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_turns_call ON turns (call_id);

CREATE TABLE IF NOT EXISTS tool_calls (
    event_key   TEXT PRIMARY KEY,
    call_id     TEXT NOT NULL,
    tool        TEXT NOT NULL,
    args_json   TEXT,
    ms          REAL,
    ok          INTEGER,  -- NULL still running, 1 returned, 0 failed
    ts          TEXT
);
CREATE INDEX IF NOT EXISTS idx_tool_calls_call ON tool_calls (call_id);

CREATE TABLE IF NOT EXISTS submissions (
    event_key   TEXT PRIMARY KEY,
    call_id     TEXT NOT NULL,
    route       TEXT,
    action      TEXT,
    status      TEXT,
    payload_json TEXT,
    ts          TEXT
);
CREATE INDEX IF NOT EXISTS idx_submissions_call ON submissions (call_id);

CREATE TABLE IF NOT EXISTS usage (
    call_id         TEXT PRIMARY KEY,
    payload_json    TEXT NOT NULL,
    stt_seconds     REAL NOT NULL DEFAULT 0,
    llm_tokens_in   INTEGER NOT NULL DEFAULT 0,
    llm_tokens_out  INTEGER NOT NULL DEFAULT 0,
    tts_characters  INTEGER NOT NULL DEFAULT 0,
    ts              TEXT
);
"""

#: Duration histogram edges, in milliseconds. A call is capped at three
#: minutes, so the last bucket is the "hit the cap" one.
DURATION_EDGES_MS = (15_000, 30_000, 60_000, 90_000, 120_000, 180_000)
DURATION_LABELS = ("<15s", "15–30s", "30–60s", "1–1.5m", "1.5–2m", "2–3m", "3m+")

#: How the stored outcome key reads on screen is the client's job; the store
#: only reproduces ``view.CallCard.status`` + the ``insights.outcomes`` rule
#: (a prepared action that never reached /submit counts as "ended").
_OUTCOME_BY_ACTION = {
    "book": "booked",
    "register": "registered",
    "reschedule": "rescheduled",
    "cancel": "cancelled",
    "no-action": "refused",
    "escalate": "escalated",
}

_SPEAKER = {"user": "user", "caller": "user", "assistant": "assistant", "agent": "assistant"}


def default_db_path(log_path: Path | None = None) -> Path:
    """``logs/calls.db`` — or ``VORTEX_CALLS_DB`` when set, or a ``calls.db``
    next to whichever log path the caller passes in (tests point the log at a
    tmp dir and get a tmp DB for free)."""
    override = os.environ.get("VORTEX_CALLS_DB", "").strip()
    if override:
        return Path(override)
    if log_path is None:
        from vortex.settings import get_settings

        log_path = get_settings().calls_log_path
    return Path(log_path).with_name("calls.db")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # WAL so the board can serve reads while a tail ingest writes;
    # busy_timeout so a read landing mid-commit waits instead of erroring.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    return conn


def _norm_ts(value: Any) -> str | None:
    """Normalise to UTC ISO-8601 ms so a plain string compare orders every
    timestamp — the log mixes ``+02:00`` synthetic stamps with ``+00:00``
    live ones."""
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp.astimezone(UTC).isoformat(timespec="milliseconds")


def _ensure_call(conn: sqlite3.Connection, call_id: str) -> None:
    conn.execute("INSERT OR IGNORE INTO calls (call_id) VALUES (?)", (call_id,))


def _route_tail(route: Any) -> str | None:
    """``/api/v1/submit/no-action`` -> ``no-action``; the action a submission
    asked for, the way ``view.build_call`` reads it."""
    if not isinstance(route, str) or not route:
        return None
    tail = route.rstrip("/").rsplit("/", 1)[-1]
    return tail or None


def _submit_status(result: Any) -> str | None:
    if isinstance(result, dict) and result.get("status"):
        return str(result["status"])
    if isinstance(result, str) and result:
        return result
    return None


def _fold_event(conn: sqlite3.Connection, event: dict[str, Any], event_key: str) -> None:
    """One new JSONL event into the derived tables. Only ever called for a
    line whose digest just inserted into ``events`` — that is what makes the
    whole pipeline idempotent. ``event_key`` is that digest, reused as the
    primary key of every row the event produces."""
    call_id = str(event.get("call_id") or "?")
    kind = str(event.get("kind") or "")
    ts = _norm_ts(event.get("ts"))
    if call_id == "?":
        return
    _ensure_call(conn, call_id)
    conn.execute("UPDATE calls SET events = events + 1 WHERE call_id = ?", (call_id,))

    if kind == "call.started":
        conn.execute(
            "UPDATE calls SET started_ts = ?, from_masked = ?, problem_id = ? WHERE call_id = ?",
            (
                ts or _norm_ts(event.get("connected_at")),
                mask_phone(event.get("from_number")) if event.get("from_number") else None,
                event.get("problem_id"),
                call_id,
            ),
        )
    elif kind == "call.intent":
        intent = str(event.get("intent") or "").strip()
        if intent:
            conn.execute("UPDATE calls SET intent = ? WHERE call_id = ?", (intent, call_id))
    elif kind in {"turn.user", "turn.assistant"}:
        text = str(event.get("text") or "")
        conn.execute(
            "INSERT OR IGNORE INTO turns"
            " (event_key, call_id, speaker, text, words, started_ts, measured)"
            " VALUES (?, ?, ?, ?, ?, ?, 0)",
            (
                event_key,
                call_id,
                "user" if kind == "turn.user" else "assistant",
                text,
                len(text.split()),
                ts,
            ),
        )
    elif kind == "turn.metrics":
        speaker = _SPEAKER.get(str(event.get("speaker") or "").lower())
        if speaker is None:
            return
        words = event.get("words")
        conn.execute(
            "INSERT OR IGNORE INTO turns"
            " (event_key, call_id, speaker, words, started_ts, ended_ts, ttfb_ms, measured)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (
                event_key,
                call_id,
                speaker,
                int(words) if words is not None else 0,
                _norm_ts(event.get("started_ts")),
                _norm_ts(event.get("ended_ts")),
                float(event["ttfb_ms"]) if event.get("ttfb_ms") is not None else None,
            ),
        )
    elif kind == "tool.called":
        conn.execute(
            "INSERT OR IGNORE INTO tool_calls (event_key, call_id, tool, args_json, ts)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                event_key,
                call_id,
                str(event.get("tool") or "?"),
                json.dumps(event.get("args"), ensure_ascii=False),
                ts,
            ),
        )
    elif kind in {"tool.returned", "tool.failed"}:
        tool = str(event.get("tool") or "")
        ok = 1 if kind == "tool.returned" else 0
        ms = event.get("ms")
        # Pair with the most recent still-open call for this tool, the same
        # match ``view.build_call`` makes. No open row: the finish event keys
        # its own row so the sample is never lost.
        row = conn.execute(
            "SELECT event_key FROM tool_calls"
            " WHERE call_id = ? AND tool = ? AND ok IS NULL"
            " ORDER BY rowid DESC LIMIT 1",
            (call_id, tool),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT OR IGNORE INTO tool_calls (event_key, call_id, tool, ms, ok, ts)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    event_key,
                    call_id,
                    tool or "?",
                    float(ms) if ms is not None else None,
                    ok,
                    ts,
                ),
            )
        else:
            conn.execute(
                "UPDATE tool_calls SET ms = ?, ok = ? WHERE event_key = ?",
                (float(ms) if ms is not None else None, ok, row["event_key"]),
            )
    elif kind in {"submit.sent", "submit.result"}:
        route = event.get("route")
        conn.execute(
            "INSERT OR IGNORE INTO submissions"
            " (event_key, call_id, route, action, status, payload_json, ts)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event_key,
                call_id,
                route if isinstance(route, str) else None,
                _route_tail(route),
                _submit_status(event.get("result")),
                json.dumps(event.get("payload"), ensure_ascii=False),
                ts,
            ),
        )
        if kind == "submit.result" or _route_tail(route):
            conn.execute(
                "UPDATE calls SET submit_route = ?, submit_status = ?, action_kind = ?"
                " WHERE call_id = ?",
                (
                    route if isinstance(route, str) else None,
                    _submit_status(event.get("result")),
                    _route_tail(route),
                    call_id,
                ),
            )
    elif kind == "call.usage":
        payload = {k: v for k, v in event.items() if k not in {"ts", "call_id", "kind"}}
        stt = payload.get("stt") if isinstance(payload.get("stt"), dict) else {}
        llm = payload.get("llm") if isinstance(payload.get("llm"), dict) else {}
        tts = payload.get("tts") if isinstance(payload.get("tts"), list) else []
        conn.execute(
            "INSERT OR REPLACE INTO usage"
            " (call_id, payload_json, stt_seconds, llm_tokens_in, llm_tokens_out,"
            "  tts_characters, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                call_id,
                json.dumps(payload, ensure_ascii=False),
                float(stt.get("audio_seconds") or 0.0),
                int(llm.get("prompt_tokens") or 0),
                int(llm.get("completion_tokens") or 0),
                sum(int(leg.get("characters") or 0) for leg in tts if isinstance(leg, dict)),
                ts,
            ),
        )
    elif kind == "call.ended":
        conn.execute(
            "UPDATE calls SET ended = 1, ended_ts = ?, reason = ? WHERE call_id = ?",
            (ts, event.get("reason"), call_id),
        )
    elif kind == "call.summary":
        duration = event.get("duration_ms")
        conn.execute(
            "UPDATE calls SET ended = 1, ended_ts = ?, duration_ms = ?,"
            " reason = COALESCE(?, reason) WHERE call_id = ?",
            (ts, float(duration) if duration is not None else None, event.get("reason"), call_id),
        )
        actions = event.get("actions")
        if isinstance(actions, list) and actions:
            last = actions[-1]
            if isinstance(last, dict) and _route_tail(last.get("route")):
                conn.execute(
                    "UPDATE calls SET submit_route = COALESCE(submit_route, ?),"
                    " action_kind = COALESCE(action_kind, ?) WHERE call_id = ?",
                    (last.get("route"), _route_tail(last.get("route")), call_id),
                )
    elif kind == "call.recording":
        conn.execute(
            "UPDATE calls SET recording_path = ?, recording_ms = ?, recording_bytes = ?"
            " WHERE call_id = ?",
            (event.get("path"), event.get("duration_ms"), event.get("bytes"), call_id),
        )


def _digest(raw: str | bytes) -> str:
    data = raw.encode("utf-8") if isinstance(raw, str) else raw
    return hashlib.sha1(data).hexdigest()[:20]


def ingest(log_path: Path, db_path: Path | None = None) -> dict[str, Any]:
    """Tail ``log_path`` into ``db_path`` from the stored byte offset.

    Idempotent: the offset means each line is parsed once, and the
    ``events`` digest key means even a re-read line never double-counts. A
    file that shrank since the last ingest (rotated, rewritten) restarts at
    byte 0 and dedupes its way back to the same rows.
    """
    log_path = Path(log_path)
    db_path = Path(db_path) if db_path is not None else default_db_path(log_path)
    stats: dict[str, Any] = {
        "log": str(log_path),
        "db": str(db_path),
        "events_new": 0,
        "offset": 0,
    }
    conn = connect(db_path)
    try:
        if not log_path.exists():
            stats["events_total"] = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            return stats

        row = conn.execute(
            "SELECT offset FROM ingest_state WHERE path = ?", (str(log_path),)
        ).fetchone()
        offset = int(row["offset"]) if row else 0
        size = log_path.stat().st_size
        if size < offset:
            offset = 0  # rotated or rewritten: re-read; digests dedupe

        with log_path.open("rb") as fh:
            fh.seek(offset)
            chunk = fh.read()

        # Never swallow a half-written last line: consume up to the final
        # newline and leave the tail for the next poll.
        if chunk.endswith(b"\n"):
            blob = chunk
        else:
            cut = chunk.rfind(b"\n")
            blob = chunk[: cut + 1] if cut >= 0 else b""
        consumed = offset + len(blob)

        with conn:
            for raw in blob.split(b"\n"):
                line = raw.strip()
                if not line:
                    continue
                key = _digest(line)
                cur = conn.execute(
                    "INSERT OR IGNORE INTO events (event_key, call_id, kind, ts, raw)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (key, None, None, None, line.decode("utf-8", "replace")),
                )
                if cur.rowcount == 0:
                    continue  # already ingested
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                conn.execute(
                    "UPDATE events SET call_id = ?, kind = ?, ts = ? WHERE event_key = ?",
                    (event.get("call_id"), event.get("kind"), _norm_ts(event.get("ts")), key),
                )
                _fold_event(conn, event, key)
                stats["events_new"] += 1

            conn.execute(
                "INSERT INTO ingest_state (path, offset) VALUES (?, ?)"
                " ON CONFLICT(path) DO UPDATE SET offset = excluded.offset",
                (str(log_path), consumed),
            )

        stats["offset"] = consumed
        stats["events_total"] = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        stats["calls"] = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
        return stats
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Queries. Every helper takes an open connection plus ``days`` (the window,
# counted back from ``now`` on the *call start*, never on event time).
# ---------------------------------------------------------------------------


def _cutoff(days: int, now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)) - timedelta(days=days)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp.astimezone(UTC).isoformat(timespec="milliseconds")


def _window_calls(
    conn: sqlite3.Connection, days: int, now: datetime | None = None
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM calls WHERE started_ts IS NOT NULL AND started_ts >= ? ORDER BY started_ts",
        (_cutoff(days, now),),
    ).fetchall()


def _outcome(row: sqlite3.Row) -> str:
    """``view.CallCard.status`` + the ``insights.outcomes`` correction, on a
    stored row. A call that prepared an action but never sent it is "ended",
    not the action."""
    if not row["ended"]:
        return "live"
    if row["action_kind"] and not (row["submit_status"] or row["submit_route"]):
        return "ended"
    return _OUTCOME_BY_ACTION.get(row["action_kind"] or "", "ended")


def _shares(rows: list[dict[str, Any]], total: int) -> list[dict[str, Any]]:
    biggest = max((r["count"] for r in rows), default=1) or 1
    for r in rows:
        r["pct"] = round(100 * r["count"] / total, 1) if total else 0.0
        r["share"] = r["count"] / biggest
    return rows


def status_mix(
    conn: sqlite3.Connection, days: int, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Calls by outcome, most frequent first."""
    counts: dict[str, int] = {}
    calls = _window_calls(conn, days, now)
    for row in calls:
        key = _outcome(row)
        counts[key] = counts.get(key, 0) + 1
    rows = [{"key": k, "count": v} for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]
    return _shares(rows, len(calls))


def duration_buckets(
    conn: sqlite3.Connection, days: int, now: datetime | None = None
) -> dict[str, Any]:
    """Histogram over ended calls with a known duration, plus median/p90."""
    values = [
        float(r["duration_ms"])
        for r in _window_calls(conn, days, now)
        if r["ended"] and r["duration_ms"]
    ]
    edges = (*DURATION_EDGES_MS, float("inf"))
    counts = [0] * len(DURATION_LABELS)
    for ms in values:
        for i, edge in enumerate(edges):
            if ms < edge:
                counts[i] += 1
                break
    biggest = max(counts, default=1) or 1
    buckets = [
        {
            "label": label,
            "count": n,
            "share": n / biggest,
            "pct": round(100 * n / len(values), 1) if values else 0.0,
        }
        for label, n in zip(DURATION_LABELS, counts, strict=True)
    ]
    p50, p90 = percentiles([v / 1000 for v in values], 0.5, 0.9)
    return {"buckets": buckets, "n": len(values), "median_s": p50, "p90_s": p90}


def _turns_by_call(
    conn: sqlite3.Connection, days: int, now: datetime | None = None
) -> dict[str, list[sqlite3.Row]]:
    """Turn rows for in-window calls, grouped. When a call has measured
    (``turn.metrics``) rows only those count — otherwise the call falls back
    to its word-count proxy rows. Per call, never mixed."""
    rows = conn.execute(
        "SELECT t.* FROM turns t JOIN calls c ON c.call_id = t.call_id"
        " WHERE c.started_ts IS NOT NULL AND c.started_ts >= ?",
        (_cutoff(days, now),),
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row["call_id"], []).append(row)
    out: dict[str, list[sqlite3.Row]] = {}
    for call_id, turns in grouped.items():
        measured = [t for t in turns if t["measured"]]
        out[call_id] = measured or [t for t in turns if not t["measured"]]
    return out


def _turn_amount(row: sqlite3.Row) -> float:
    """Speaking time in ms for a measured row, word count for a proxy row."""
    if row["measured"] and row["started_ts"] and row["ended_ts"]:
        try:
            delta = datetime.fromisoformat(row["ended_ts"]) - datetime.fromisoformat(
                row["started_ts"]
            )
            return max(delta.total_seconds() * 1000, 0.0)
        except ValueError:
            return 0.0
    return float(row["words"] or 0)


def talk_ratio(
    conn: sqlite3.Connection, days: int, now: datetime | None = None, limit: int = 20
) -> dict[str, Any]:
    """Agent vs caller share of the conversation, per recent call and overall.

    Measured calls split by speaking time; unmeasured calls split by words.
    ``basis`` on each row says which; "time" overall once any call is measured.
    """
    starts = {r["call_id"]: r["started_ts"] for r in _window_calls(conn, days, now)}
    calls = []
    for call_id, turns in _turns_by_call(conn, days, now).items():
        agent = sum(_turn_amount(t) for t in turns if t["speaker"] == "assistant")
        caller = sum(_turn_amount(t) for t in turns if t["speaker"] == "user")
        total = agent + caller
        if total <= 0:
            continue
        calls.append(
            {
                "call_id": call_id,
                "started_ts": starts.get(call_id),
                "agent_share": agent / total,
                "caller_share": caller / total,
                "basis": "time" if turns[0]["measured"] else "words",
            }
        )
    calls.sort(key=lambda c: str(c["started_ts"] or ""), reverse=True)
    calls = calls[:limit]
    overall = None
    if calls:
        overall = {
            "agent_share": sum(c["agent_share"] for c in calls) / len(calls),
            "caller_share": sum(c["caller_share"] for c in calls) / len(calls),
            "basis": "time" if any(c["basis"] == "time" for c in calls) else "words",
        }
    return {"calls": calls, "overall": overall}


def words_per_turn(
    conn: sqlite3.Connection, days: int, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Average words per turn per speaker over each call's chosen basis."""
    totals: dict[str, list[int]] = {"user": [], "assistant": []}
    measured_any = False
    for turns in _turns_by_call(conn, days, now).values():
        measured_any = measured_any or bool(turns[0]["measured"])
        for t in turns:
            totals[t["speaker"]].append(int(t["words"] or 0))
    out = []
    for speaker, values in totals.items():
        out.append(
            {
                "speaker": speaker,
                "turns": len(values),
                "avg_words": round(sum(values) / len(values), 1) if values else None,
                "basis": "measured" if measured_any else "proxy",
            }
        )
    return out


def ttfb_percentiles(
    conn: sqlite3.Connection, days: int, now: datetime | None = None
) -> dict[str, Any]:
    """Time-to-first-byte p50/p95 over measured agent turns. ``n`` is the
    sample count so a client can say "no turn.metrics yet" when it is 0."""
    rows = conn.execute(
        "SELECT t.ttfb_ms FROM turns t JOIN calls c ON c.call_id = t.call_id"
        " WHERE t.measured = 1 AND t.ttfb_ms IS NOT NULL"
        " AND c.started_ts IS NOT NULL AND c.started_ts >= ?",
        (_cutoff(days, now),),
    ).fetchall()
    values = [float(r["ttfb_ms"]) for r in rows]
    p50, p95 = percentiles(values, 0.5, 0.95)
    return {"p50_ms": p50, "p95_ms": p95, "n": len(values)}


def tool_latency(
    conn: sqlite3.Connection, days: int, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Per-tool p50/p95 latency and failure count, slowest first."""
    rows = conn.execute(
        "SELECT t.tool, t.ms, t.ok FROM tool_calls t JOIN calls c ON c.call_id = t.call_id"
        " WHERE c.started_ts IS NOT NULL AND c.started_ts >= ?",
        (_cutoff(days, now),),
    ).fetchall()
    samples: dict[str, list[float]] = {}
    failures: dict[str, int] = {}
    calls: dict[str, int] = {}
    for r in rows:
        tool = str(r["tool"])
        calls[tool] = calls.get(tool, 0) + 1
        if r["ok"] == 0:
            failures[tool] = failures.get(tool, 0) + 1
        if r["ms"] is not None:
            samples.setdefault(tool, []).append(float(r["ms"]))
    out = []
    for tool, values in samples.items():
        p50, p95 = percentiles(values, 0.5, 0.95)
        out.append(
            {
                "tool": tool,
                "p50_ms": p50,
                "p95_ms": p95,
                "calls": calls.get(tool, 0),
                "failures": failures.get(tool, 0),
            }
        )
    for tool, n in failures.items():
        if tool not in samples:
            out.append(
                {"tool": tool, "p50_ms": None, "p95_ms": None, "calls": calls[tool], "failures": n}
            )
    out.sort(key=lambda r: -(r["p50_ms"] or 0))
    return out


def outcome_funnel(
    conn: sqlite3.Connection, days: int, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Intent → submitted action. One row per classified intent (plus
    ``null`` for calls the classifier never reached), each with how its
    calls actually ended."""
    rows = []
    for call in _window_calls(conn, days, now):
        subs = conn.execute(
            "SELECT action FROM submissions WHERE call_id = ? AND action IS NOT NULL",
            (call["call_id"],),
        ).fetchall()
        rows.append((call["intent"], [s["action"] for s in subs] or None, _outcome(call)))
    intents: dict[str | None, dict[str, Any]] = {}
    for intent, actions, outcome in rows:
        bucket = intents.setdefault(intent, {"intent": intent, "calls": 0, "by_action": {}})
        bucket["calls"] += 1
        for action in actions or [f"none:{outcome}"]:
            bucket["by_action"][action] = bucket["by_action"].get(action, 0) + 1
    return sorted(intents.values(), key=lambda r: -r["calls"])


def cost_series(conn: sqlite3.Connection, days: int, now: datetime | None = None) -> dict[str, Any]:
    """€ per call over the window — each ``call.usage`` payload re-priced by
    ``pricing.price_call``, so the store adds no cost logic of its own."""
    rows = conn.execute(
        "SELECT u.call_id, u.payload_json, c.started_ts FROM usage u"
        " JOIN calls c ON c.call_id = u.call_id"
        " WHERE c.started_ts IS NOT NULL AND c.started_ts >= ? ORDER BY c.started_ts",
        (_cutoff(days, now),),
    ).fetchall()
    points = []
    metered = priced = 0
    total = total_list = 0.0
    unpriced: set[str] = set()
    for r in rows:
        cost = price_call(json.loads(r["payload_json"]))
        if not cost.metered:
            continue
        metered += 1
        unpriced.update(cost.unpriced)
        if cost.priced:
            priced += 1
            total += cost.total_eur
            total_list += cost.total_list_eur
        points.append(
            {
                "call_id": r["call_id"],
                "ts": r["started_ts"],
                "eur": round(cost.total_eur, 5),
                "list_eur": round(cost.total_list_eur, 5),
                "priced": cost.priced,
            }
        )
    return {
        "points": points,
        "metered": metered,
        "priced": priced,
        "avg_eur": total / priced if priced else None,
        "avg_list_eur": total_list / priced if priced else None,
        "total_eur": total,
        "total_list_eur": total_list,
        "unpriced": sorted(unpriced),
    }


def analytics(db_path: Path, days: int, now: datetime | None = None) -> dict[str, Any]:
    """The whole ``/api/wall/analytics`` payload from the store."""
    conn = connect(Path(db_path))
    try:
        calls = _window_calls(conn, days, now)
        turns = _turns_by_call(conn, days, now)
        measured_calls = sum(1 for t in turns.values() if t and t[0]["measured"])
        return {
            "calls_considered": len(calls),
            "status_mix": status_mix(conn, days, now),
            "durations": duration_buckets(conn, days, now),
            "talk_ratio": talk_ratio(conn, days, now),
            "words_per_turn": words_per_turn(conn, days, now),
            "ttfb": ttfb_percentiles(conn, days, now),
            "tool_latency": tool_latency(conn, days, now),
            "funnel": outcome_funnel(conn, days, now),
            "cost": cost_series(conn, days, now),
            "metrics": {
                "measured_calls": measured_calls,
                "proxy_calls": len(turns) - measured_calls,
            },
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI — `make ingest`
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tail logs/calls.jsonl into the analytics SQLite store."
    )
    parser.add_argument("--log", type=Path, default=None, help="JSONL log (default: settings)")
    parser.add_argument(
        "--db", type=Path, default=None, help="SQLite DB (default: next to the log)"
    )
    parser.add_argument("--rebuild", action="store_true", help="drop the DB first")
    args = parser.parse_args()

    log_path = args.log
    if log_path is None:
        from vortex.settings import get_settings

        log_path = get_settings().calls_log_path
    db_path = args.db or default_db_path(log_path)
    if args.rebuild and db_path.exists():
        db_path.unlink()

    stats = ingest(log_path, db_path)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
