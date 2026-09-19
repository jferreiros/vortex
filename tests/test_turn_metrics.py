"""``turn.metrics``: the per-turn analytics row written next to each ``turn.*``.

Every ``turn.user``/``turn.assistant`` line is followed by a ``turn.metrics``
line carrying ``speaker``, ``started_ts``, ``ended_ts`` and ``words``; agent
turns also carry ``ttfb_ms``. The shape is what the analytics queries group
by, so it is pinned here.
"""

from __future__ import annotations

import json
from pathlib import Path

from vortex.line.turnclock import TurnClock
from vortex.observability.calllog import CallLog


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_every_turn_gets_a_metrics_line(tmp_path: Path) -> None:
    log = CallLog("CA-m", tmp_path / "calls.jsonl")
    log.user_turn("quiero una cita")
    log.assistant_turn("claro, ¿para qué día?")

    lines = _lines(tmp_path / "calls.jsonl")
    kinds = [line["kind"] for line in lines]
    assert kinds == ["turn.user", "turn.metrics", "turn.assistant", "turn.metrics"]

    user_metrics = lines[1]
    assert user_metrics["speaker"] == "user"
    assert user_metrics["words"] == 3
    assert user_metrics["started_ts"] <= user_metrics["ended_ts"]
    # TTFB is an agent-turn field only.
    assert "ttfb_ms" not in user_metrics

    agent_metrics = lines[3]
    assert agent_metrics["speaker"] == "assistant"
    assert agent_metrics["words"] == 4
    # The first answer after a caller turn carries the reply latency.
    assert isinstance(agent_metrics["ttfb_ms"], (int, float))
    assert agent_metrics["ttfb_ms"] >= 0


def test_an_answer_with_no_prior_user_turn_reports_no_ttfb(tmp_path: Path) -> None:
    """The greeting is nobody's reply: ttfb_ms is null, never missing."""
    log = CallLog("CA-g", tmp_path / "calls.jsonl")
    log.assistant_turn("Buenas, clínica Arenal, ¿en qué puedo ayudarle?")

    metrics = _lines(tmp_path / "calls.jsonl")[-1]
    assert metrics["kind"] == "turn.metrics"
    assert metrics["speaker"] == "assistant"
    assert metrics["ttfb_ms"] is None


def test_only_the_first_chunk_of_a_reply_carries_ttfb(tmp_path: Path) -> None:
    log = CallLog("CA-t", tmp_path / "calls.jsonl")
    log.user_turn("hola")
    log.assistant_turn("hola, dígame")
    log.assistant_turn("¿qué necesita?")

    metrics = [line for line in _lines(tmp_path / "calls.jsonl") if line["kind"] == "turn.metrics"]
    assert metrics[1]["ttfb_ms"] is not None
    assert metrics[2]["ttfb_ms"] is None


def test_pipeline_supplied_bounds_win(tmp_path: Path) -> None:
    log = CallLog("CA-b", tmp_path / "calls.jsonl")
    log.user_turn("hola", started_ts="2026-09-19T10:00:00.000+00:00")
    log.assistant_turn(
        "hola",
        started_ts="2026-09-19T10:00:02.000+00:00",
        ended_ts="2026-09-19T10:00:03.500+00:00",
        ttfb_ms=1800.0,
    )

    metrics = [line for line in _lines(tmp_path / "calls.jsonl") if line["kind"] == "turn.metrics"]
    assert metrics[0]["started_ts"] == "2026-09-19T10:00:00.000+00:00"
    assert metrics[1]["started_ts"] == "2026-09-19T10:00:02.000+00:00"
    assert metrics[1]["ended_ts"] == "2026-09-19T10:00:03.500+00:00"
    assert metrics[1]["ttfb_ms"] == 1800.0


def test_turnclock_bounds_a_conversation() -> None:
    clock = TurnClock()
    clock.on_user_speech_start()
    started, ended = clock.user_bounds()
    assert started <= ended

    clock.on_user_turn_end()
    clock.on_agent_response_start()
    started, ended, ttfb = clock.assistant_bounds()
    assert started <= ended
    assert ttfb is not None and ttfb >= 0

    # A second chunk of the same answer starts where the first ended - and
    # the TTFB is spent.
    started2, ended2, ttfb2 = clock.assistant_bounds()
    assert started2 == ended
    assert ttfb2 is None
