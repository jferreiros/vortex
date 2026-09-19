from __future__ import annotations

from vortex.observability.view import Turn, build_call, fold_turns


def test_fold_turns_drops_exact_and_replayed_bubbles() -> None:
    turns = [
        Turn("assistant", "Clínica Arenal, hello. How can I help you?"),
        Turn("assistant", "Clínica Arenal, hello. How can I help you?"),
        Turn("assistant", "Clínica Arenal, hello. How can I help you?"),
        Turn("user", "Hello."),
        Turn("user", "Hello."),
        Turn("assistant", "Hello."),
        Turn("assistant", "How can I help you today?"),
        Turn("assistant", "Hello."),
        Turn("assistant", "How can I help you today?"),
        Turn("user", "Yeah"),
        Turn("user", "Yeah, so, I need an orthopedics appointment."),
    ]
    folded = fold_turns(turns)
    texts = [turn.text for turn in folded]
    assert texts == [
        "Clínica Arenal, hello. How can I help you?",
        "Hello.",
        "Hello.",
        "How can I help you today?",
        "Yeah, so, I need an orthopedics appointment.",
    ]
    assert [turn.role for turn in folded] == [
        "assistant",
        "user",
        "assistant",
        "assistant",
        "user",
    ]


def test_fold_turns_does_not_merge_yes_into_yesterday() -> None:
    turns = [
        Turn("user", "Yes"),
        Turn("user", "Yesterday works"),
    ]
    folded = fold_turns(turns)
    assert [turn.text for turn in folded] == ["Yes", "Yesterday works"]


def test_build_call_folds_turns_and_clears_stale_decline_on_book() -> None:
    card = build_call(
        "CA-1",
        [
            {"kind": "turn.assistant", "ts": "t1", "text": "Hello."},
            {"kind": "turn.assistant", "ts": "t2", "text": "Hello."},
            {"kind": "turn.user", "ts": "t3", "text": "Hi"},
            {
                "kind": "tool.returned",
                "ts": "t4",
                "tool": "find_slots",
                "result": {"status": "none", "reason": "no_availability"},
            },
            {
                "kind": "submit.result",
                "ts": "t5",
                "route": "/api/v1/submit/book",
                "result": {"status": "accepted"},
                "payload": {"patient_id": "P1"},
            },
            {"kind": "call.ended", "ts": "t6"},
        ],
    )
    assert [turn.text for turn in card.turns] == ["Hello.", "Hi"]
    assert card.status == "booked"
    assert card.decline_reason is None


def test_build_call_folds_the_usage_event_into_the_card() -> None:
    """The line lane writes call.usage just before call.ended; the card keeps it
    whole, minus the envelope, so pricing reads one payload."""
    card = build_call(
        "CA-2",
        [
            {"kind": "call.started", "call_id": "CA-2", "ts": "t1"},
            {
                "kind": "call.usage",
                "call_id": "CA-2",
                "ts": "t2",
                "metered": True,
                "stt": {"provider": "soniox", "model": "stt-rt-v5", "audio_seconds": 47.3},
                "llm": {"provider": "helmcode", "model": "deepseek-v4-flash"},
                "tts": [{"provider": "google", "model": "es-ES-Chirp3-HD-A", "characters": 1180}],
            },
            {"kind": "call.ended", "call_id": "CA-2", "ts": "t3"},
        ],
    )
    assert card.usage is not None
    assert card.usage["metered"] is True
    assert card.usage["stt"]["audio_seconds"] == 47.3
    assert card.usage["tts"][0]["characters"] == 1180
    # The envelope stays out: pricing reads counters, not routing fields.
    assert "call_id" not in card.usage
    assert "kind" not in card.usage
    assert "ts" not in card.usage


def test_a_call_with_no_usage_event_has_no_usage() -> None:
    card = build_call("CA-3", [{"kind": "call.started", "call_id": "CA-3"}])
    assert card.usage is None
