from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from vortex.line.session import CallSession
from vortex.line.twilio import StartPayload
from vortex.observability import discord_calls
from vortex.settings import Settings

NOW = datetime(2026, 9, 19, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))


def _session(tmp_path: Path) -> CallSession:
    start = StartPayload.model_validate(
        {
            "streamSid": "MZ-discord",
            "callSid": "CA-discord",
            "customParameters": {"from_number": "+34600111222"},
        }
    )
    return CallSession.open(
        start,
        settings=Settings(),
        now=NOW,
    )


def test_card_from_session_drops_the_number_and_keeps_the_action(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.end_reason = "socket_closed"
    session.ctx.log.action_submitted(
        "/api/v1/submit/book",
        {
            "kind": "book",
            "patient_id": "P00042",
            "provider_id": "PR01",
            "location_id": "centro",
            "national_id": "12345678Z",
            "given_name": "Ana",
        },
        {"status": "accepted"},
    )
    card = discord_calls.card_from_session(session)
    dumped = str(card)
    assert "+34600111222" not in dumped
    assert "12345678Z" not in dumped
    assert "Ana" not in dumped
    assert "P00042" not in dumped
    assert card["kind"] == "book"
    assert card["action"]["provider_id"] == "PR01"
    assert card["submit_status"] == "accepted"


def test_webhook_body_has_no_pii_and_links_the_wall() -> None:
    body = discord_calls.webhook_body(
        {
            "call_id": "CA-safe",
            "status": "booked",
            "kind": "book",
            "reason": "",
            "submit_status": "accepted",
            "duration_ms": 42000,
            "turns": 6,
            "user_turns": 3,
            "tools": 4,
            "tool_names": ["find_patient", "find_slots"],
            "action": {"kind": "book", "location_id": "norte"},
            "voice": "pipecat",
            "clinic": "live",
            "llm": "helmcode/deepseek-v4-flash",
        },
        wall="https://example.test/wall",
    )
    discord_calls.assert_no_pii(body)
    embed = body["embeds"][0]
    assert embed["url"] == "https://example.test/wall"
    assert "book" in embed["title"]
    assert "norte" in embed["description"]
    assert "langfuse" in embed["footer"]["text"]


def test_digest_counts_kinds_and_stays_red_when_one_call_crashed() -> None:
    body = discord_calls.digest_body(
        [
            {
                "call_id": "a",
                "status": "booked",
                "kind": "book",
                "reason": "",
                "duration_ms": 1000,
                "tools": 2,
            },
            {
                "call_id": "b",
                "status": "crashed",
                "kind": "no-action",
                "reason": "crashed",
                "duration_ms": 2000,
                "tools": 0,
            },
        ],
        wall="https://example.test/wall",
    )
    assert "2 llamadas" in body["content"]
    assert "book 1" in body["content"]
    assert body["embeds"][0]["color"] == 0xE23D4A


def test_calls_webhook_wins_over_github(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_CALLS_WEBHOOK_URL", "https://example.test/calls")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.test/github")
    assert discord_calls.webhook_url() == "https://example.test/calls"


def test_notify_is_a_noop_under_pytest(tmp_path: Path) -> None:
    assert discord_calls.enabled() is False
    discord_calls.notify_session(_session(tmp_path))


def test_cards_from_events_ignore_transcript_text() -> None:
    started = {
        "ts": "2026-09-19T08:00:00Z",
        "call_id": "c1",
        "kind": "call.started",
        "from_number": "+34600111222",
        "voice": "pipecat",
        "clinic": "live",
    }
    turn = {
        "ts": "2026-09-19T08:00:01Z",
        "call_id": "c1",
        "kind": "turn.user",
        "text": "Soy Ana García, DNI 12345678Z",
    }
    submit = {
        "ts": "2026-09-19T08:00:02Z",
        "call_id": "c1",
        "kind": "submit.result",
        "route": "/api/v1/submit/no-action",
        "payload": {"reason": "no_availability"},
        "result": {"status": "accepted"},
    }
    summary = {
        "ts": "2026-09-19T08:00:03Z",
        "call_id": "c1",
        "kind": "call.summary",
        "duration_ms": 3000,
        "reason": "socket_closed",
    }
    cards = discord_calls.cards_from_events([started, turn, submit, summary])
    body = discord_calls.digest_body(cards, wall="https://example.test/wall")
    dumped = str(body)
    assert "Ana" not in dumped
    assert "12345678Z" not in dumped
    assert "+34600111222" not in dumped
    assert "no_availability" in dumped
