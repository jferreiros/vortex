"""The analytics SQLite store — ingest idempotency and the aggregates behind
``/api/wall/analytics``.

``store.ingest`` tails ``calls.jsonl`` from a byte offset it keeps inside the
DB itself, so these tests pin the two properties the endpoint relies on:
re-ingesting is a no-op, and calls logged before the ``turn.metrics`` events
existed still produce talk-ratio and words-per-turn numbers (word-count
proxies) instead of empty panels.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from nicegui.testing import User

from vortex.observability import store
from vortex.settings import REPO_ROOT

SYNTHETIC_LOGS = REPO_ROOT / "synthetic-data" / "logs"
#: Fixed clock for the helper-level tests: the seeded calls sit at
#: 2026-09-19/20, one day inside every window the tests open.
NOW = datetime(2026, 9, 20, tzinfo=UTC)


def _line(ts: str, call_id: str, kind: str, **data: object) -> str:
    return json.dumps({"ts": ts, "call_id": call_id, "kind": kind, **data})


def _seed_call(
    path: Path,
    cid: str,
    *,
    day: str = "2026-09-19",
    route: str = "/api/v1/submit/book",
    intent: str | None = "book",
    metrics: bool = False,
    usage: bool = False,
) -> None:
    """Append one complete call: start, two turns, a tool, a submission, end."""
    lines = [
        _line(f"{day}T10:00:00.000+00:00", cid, "call.started", from_number="+34612345678"),
    ]
    if intent:
        lines.append(_line(f"{day}T10:00:01.000+00:00", cid, "call.intent", intent=intent))
    lines += [
        _line(f"{day}T10:00:02.000+00:00", cid, "turn.user", text="quiero una cita"),
        _line(
            f"{day}T10:00:06.000+00:00",
            cid,
            "turn.assistant",
            text="por supuesto, con qué médico",
        ),
        _line(f"{day}T10:00:08.000+00:00", cid, "tool.called", tool="find_patient", args={}),
        _line(
            f"{day}T10:00:09.000+00:00",
            cid,
            "tool.returned",
            tool="find_patient",
            result={"patient": None},
            ms=180.0,
        ),
    ]
    if metrics:
        lines += [
            _line(
                f"{day}T10:00:02.000+00:00",
                cid,
                "turn.metrics",
                speaker="user",
                started_ts=f"{day}T10:00:02.000+00:00",
                ended_ts=f"{day}T10:00:05.000+00:00",
                words=4,
            ),
            _line(
                f"{day}T10:00:06.000+00:00",
                cid,
                "turn.metrics",
                speaker="assistant",
                started_ts=f"{day}T10:00:06.000+00:00",
                ended_ts=f"{day}T10:00:10.000+00:00",
                words=6,
                ttfb_ms=420.0,
            ),
        ]
    lines.append(
        _line(
            f"{day}T10:00:12.000+00:00",
            cid,
            "submit.result",
            route=route,
            payload={"reason": "no_availability"},
            result={"status": "accepted"},
        )
    )
    if usage:
        lines.append(
            _line(
                f"{day}T10:00:14.000+00:00",
                cid,
                "call.usage",
                metered=True,
                stt={"provider": "soniox", "model": "stt-rt-v5", "audio_seconds": 14.0},
                llm={
                    "provider": "helmcode",
                    "model": "deepseek-v4-flash",
                    "prompt_tokens": 3000,
                    "completion_tokens": 120,
                },
                tts=[
                    {
                        "provider": "google",
                        "model": "es-ES-Chirp3-HD-Aoede",
                        "characters": 60,
                    }
                ],
            )
        )
    lines += [
        _line(f"{day}T10:00:15.000+00:00", cid, "call.ended", reason="hangup"),
        _line(f"{day}T10:00:16.000+00:00", cid, "call.summary", duration_ms=16000, turns=2),
    ]
    with path.open("a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line + "\n")


@pytest.fixture
def log_and_db(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "calls.jsonl", tmp_path / "calls.db"


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def test_ingest_is_idempotent_and_offset_tracked(log_and_db) -> None:
    log_path, db_path = log_and_db
    _seed_call(log_path, "CA-1")

    first = store.ingest(log_path, db_path)
    assert first["events_new"] == 9
    assert first["calls"] == 1

    second = store.ingest(log_path, db_path)
    assert second["events_new"] == 0
    assert second["events_total"] == first["events_total"]

    conn = store.connect(db_path)
    try:
        # One row per parsed event, one per derived artefact — never doubled.
        for table, expected in (
            ("calls", 1),
            ("turns", 2),
            ("tool_calls", 1),
            ("submissions", 1),
        ):
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert n == expected, table
        # The tool.called row was paired in place by tool.returned.
        row = conn.execute("SELECT ms, ok FROM tool_calls").fetchone()
        assert row["ms"] == 180.0 and row["ok"] == 1
    finally:
        conn.close()


def test_ingest_tails_only_new_lines(log_and_db) -> None:
    log_path, db_path = log_and_db
    _seed_call(log_path, "CA-1")
    store.ingest(log_path, db_path)
    _seed_call(log_path, "CA-2")

    stats = store.ingest(log_path, db_path)
    assert stats["events_new"] == 9
    assert stats["calls"] == 2


def test_ingest_recovers_from_a_rewritten_log(log_and_db) -> None:
    """A file that shrank (rotated, re-generated) restarts at byte 0 and
    digest keys keep the rows it re-reads from counting twice."""
    log_path, db_path = log_and_db
    _seed_call(log_path, "CA-1")
    _seed_call(log_path, "CA-2")
    store.ingest(log_path, db_path)

    log_path.write_text("", encoding="utf-8")
    _seed_call(log_path, "CA-2")  # same events as before: digests dedupe
    stats = store.ingest(log_path, db_path)
    assert stats["events_new"] == 0  # CA-2's lines were already in `events`
    assert stats["calls"] == 2


def test_schema_and_phone_masking(log_and_db) -> None:
    log_path, db_path = log_and_db
    _seed_call(log_path, "CA-1")
    store.ingest(log_path, db_path)

    conn = sqlite3.connect(db_path)
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert {
        "ingest_state",
        "events",
        "calls",
        "turns",
        "tool_calls",
        "submissions",
        "usage",
    } <= tables
    conn.close()

    conn = store.connect(db_path)
    try:
        row = conn.execute("SELECT from_masked, intent, ended, action_kind FROM calls").fetchone()
        assert row["ended"] == 1 and row["action_kind"] == "book" and row["intent"] == "book"
        assert "•" in row["from_masked"] and "612345678" not in row["from_masked"]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------


def test_aggregates_on_a_seeded_log(log_and_db) -> None:
    log_path, db_path = log_and_db
    _seed_call(log_path, "CA-1", route="/api/v1/submit/book")
    _seed_call(log_path, "CA-2", route="/api/v1/submit/no-action", intent="cancel")
    store.ingest(log_path, db_path)
    conn = store.connect(db_path)
    try:
        mix = store.status_mix(conn, 30, NOW)
        assert {r["key"]: r["count"] for r in mix} == {"booked": 1, "refused": 1}

        durations = store.duration_buckets(conn, 30, NOW)
        assert durations["n"] == 2 and durations["median_s"] == 16.0
        assert sum(b["count"] for b in durations["buckets"]) == 2
        assert durations["buckets"][1]["count"] == 2  # 15–30s

        ratio = store.talk_ratio(conn, 30, NOW)
        assert ratio["overall"]["basis"] == "words"
        assert 0 < ratio["overall"]["agent_share"] < 1
        assert {c["call_id"] for c in ratio["calls"]} == {"CA-1", "CA-2"}

        wpt = {r["speaker"]: r["avg_words"] for r in store.words_per_turn(conn, 30, NOW)}
        assert wpt["user"] == 3.0 and wpt["assistant"] == 5.0

        assert store.ttfb_percentiles(conn, 30, NOW) == {"p50_ms": None, "p95_ms": None, "n": 0}

        latency = store.tool_latency(conn, 30, NOW)
        assert latency[0]["tool"] == "find_patient" and latency[0]["p50_ms"] == 180.0

        funnel = {r["intent"]: r["by_action"] for r in store.outcome_funnel(conn, 30, NOW)}
        assert funnel["book"] == {"book": 1}
        assert funnel["cancel"] == {"no-action": 1}
    finally:
        conn.close()


def test_turn_metrics_take_over_from_word_proxies(log_and_db) -> None:
    """With ``turn.metrics`` rows present the aggregates switch basis: talk
    ratio splits by speaking time and TTFB percentiles appear."""
    log_path, db_path = log_and_db
    _seed_call(log_path, "CA-1", metrics=True)
    store.ingest(log_path, db_path)
    conn = store.connect(db_path)
    try:
        ratio = store.talk_ratio(conn, 30, NOW)
        call = ratio["calls"][0]
        assert call["basis"] == "time"
        # caller 3 s vs agent 4 s of speaking time
        assert call["caller_share"] == pytest.approx(3 / 7)
        assert call["agent_share"] == pytest.approx(4 / 7)

        assert store.ttfb_percentiles(conn, 30, NOW)["p50_ms"] == 420.0
        wpt = {r["speaker"]: r["avg_words"] for r in store.words_per_turn(conn, 30, NOW)}
        assert wpt["assistant"] == 6.0  # measured words, not the text count
    finally:
        conn.close()


def test_cost_series_prices_metered_calls(log_and_db) -> None:
    log_path, db_path = log_and_db
    _seed_call(log_path, "CA-1", usage=True)
    _seed_call(log_path, "CA-2")  # unmetered: stays out of every average
    store.ingest(log_path, db_path)
    conn = store.connect(db_path)
    try:
        cost = store.cost_series(conn, 30, NOW)
        assert cost["metered"] == 1 and cost["priced"] == 1
        assert cost["points"][0]["eur"] > 0
        assert cost["avg_eur"] == pytest.approx(cost["points"][0]["eur"], abs=1e-4)
        # LLM is a Helmcode perk: paid < list.
        assert cost["points"][0]["eur"] < cost["points"][0]["list_eur"]
    finally:
        conn.close()


def test_window_cutoff_uses_call_start(log_and_db) -> None:
    log_path, db_path = log_and_db
    _seed_call(log_path, "CA-old", day="2026-08-01")
    _seed_call(log_path, "CA-new", day="2026-09-19")
    store.ingest(log_path, db_path)
    conn = store.connect(db_path)
    try:
        mix7 = {r["key"]: r["count"] for r in store.status_mix(conn, 7, NOW)}
        assert sum(mix7.values()) == 1
        mix90 = {r["key"]: r["count"] for r in store.status_mix(conn, 90, NOW)}
        assert sum(mix90.values()) == 2
    finally:
        conn.close()


def test_rebuild_reproduces_the_same_aggregates(log_and_db) -> None:
    """The DB is a rebuildable query layer: delete, re-ingest, same numbers."""
    log_path, db_path = log_and_db
    _seed_call(log_path, "CA-1", usage=True, metrics=True)
    store.ingest(log_path, db_path)
    before = store.analytics(db_path, 30, NOW)

    db_path.unlink()
    store.ingest(log_path, db_path)
    after = store.analytics(db_path, 30, NOW)
    assert after == before


def test_ingest_a_missing_log_is_a_noop(log_and_db) -> None:
    log_path, db_path = log_and_db
    stats = store.ingest(log_path, db_path)
    assert stats["events_new"] == 0 and stats["events_total"] == 0


def test_synthetic_fixture_ingests_whole(log_and_db) -> None:
    """The checked-in corpus: every call parsed, outcomes match its submits."""
    _log_path, db_path = log_and_db
    stats = store.ingest(SYNTHETIC_LOGS / "clinic_day.jsonl", db_path)
    assert stats["calls"] == 60

    conn = store.connect(db_path)
    try:
        mix = {r["key"]: r["count"] for r in store.status_mix(conn, 3650)}
        assert mix["booked"] == 38 and sum(mix.values()) == 60
        assert store.duration_buckets(conn, 3650)["n"] == 60
        # No turn.metrics in the corpus: the proxy path is what feeds the page.
        assert store.ttfb_percentiles(conn, 3650)["n"] == 0
        assert store.talk_ratio(conn, 3650)["overall"]["basis"] == "words"
    finally:
        conn.close()


def test_usage_fixture_prices_calls(log_and_db) -> None:
    _log_path, db_path = log_and_db
    store.ingest(SYNTHETIC_LOGS / "cancellation_demo.jsonl", db_path)
    conn = store.connect(db_path)
    try:
        cost = store.cost_series(conn, 3650)
        assert cost["metered"] == 7
        assert cost["avg_eur"] and cost["avg_eur"] > 0
        # The Gemini TTS leg has no verified price: partial calls are flagged,
        # not silently averaged as zero.
        assert any("TTS" in label for label in cost["unpriced"])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# The endpoint, inside the NiceGUI simulation
# ---------------------------------------------------------------------------


async def test_analytics_endpoint_tails_the_log_and_serves_aggregates(
    user: User, offline_settings
) -> None:
    path = Path(offline_settings.calls_log_path)
    today = datetime.now(UTC).date().isoformat()
    _seed_call(path, "CA-1", day=today)
    _seed_call(
        path, "CA-2", day=today, route="/api/v1/submit/no-action", intent="cancel", usage=True
    )

    resp = await user.http_client.get("/api/wall/analytics?days=30")
    assert resp.status_code == 200
    body = resp.json()

    assert body["range_days"] == 30
    assert body["calls_considered"] == 2
    assert body["ingest"]["events_new"] > 0
    assert {r["key"]: r["count"] for r in body["status_mix"]} == {"booked": 1, "refused": 1}
    assert body["durations"]["n"] == 2
    assert body["cost"]["metered"] == 1

    # Second poll: ingest is a no-op, aggregates unchanged.
    again = (await user.http_client.get("/api/wall/analytics?days=30")).json()
    assert again["ingest"]["events_new"] == 0
    assert again["status_mix"] == body["status_mix"]
