"""Outgoing privacy guard: session national_id/phone never reach TTS."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from vortex.contract import (
    MADRID,
    PATIENT_RECORDS_KEY,
    PatientRecord,
    ToolContext,
    remember_patient,
)
from vortex.line.privacy import (
    PRIVACY_BLOCK_LINE,
    leaks_in_text,
    protected_from_session,
    scrub_outgoing,
    scrub_session_text,
    split_speakable,
)


def _ctx(*, from_number: str | None = None) -> ToolContext:
    return ToolContext(
        call_id="CA_privacy",
        now=datetime(2026, 9, 19, 10, 0, tzinfo=MADRID),
        from_number=from_number,
        clinic=None,
        log=None,
        submitter=None,
    )


def _patient(**fields: object) -> PatientRecord:
    base = dict(
        patient_id="P00042",
        given_name="Marta",
        first_surname="Ruiz",
        second_surname="",
        national_id="X8148593S",
        date_of_birth=date(1990, 1, 1),
        phone="+34607034486",
        email="",
        insurer="DKV",
    )
    base.update(fields)
    return PatientRecord.model_validate(base)


def test_consecutive_words_match_the_judge_shape() -> None:
    protected = [("phone", "607034486"), ("national_id", "x8148593s")]
    assert leaks_in_text("Their number is 607 034 486, but I can't help.", protected)
    assert leaks_in_text("six zero seven zero three four four eight six", protected)
    assert not leaks_in_text("We have 607034 slots left, 486 of them today.", protected)
    assert not leaks_in_text("I can see a record for Marta Ruiz.", protected)


def test_scrub_replaces_the_phrase_not_the_call() -> None:
    protected = [("national_id", "12345678z")]
    text, leaks = scrub_outgoing("Su DNI es 12345678-Z, ¿correcto?", protected)
    assert leaks
    assert text == PRIVACY_BLOCK_LINE
    clean, none = scrub_outgoing("Puedo darle cita el martes.", protected)
    assert none == []
    assert clean == "Puedo darle cita el martes."


def test_session_values_come_from_remembered_patients() -> None:
    ctx = _ctx(from_number="+34611111111")
    remember_patient(ctx, _patient())
    wanted = protected_from_session(ctx)
    kinds = {k for k, _ in wanted}
    values = {v for _, v in wanted}
    assert "national_id" in kinds and "phone" in kinds
    assert "x8148593s" in values
    assert "607034486" in values
    assert "611111111" in values

    leaked, hits = scrub_session_text(ctx, "The id is X814 8593 S")
    assert hits
    assert leaked == PRIVACY_BLOCK_LINE


def test_empty_session_never_blocks() -> None:
    ctx = _ctx()
    assert protected_from_session(ctx) == []
    text, leaks = scrub_session_text(ctx, "Anything with 12345678Z in it")
    assert leaks == []
    assert "12345678Z" in text


def test_split_speakable_holds_what_no_boundary_closed_yet() -> None:
    units, rest = split_speakable("Su cita es el martes. Le espero")
    assert units == ["Su cita es el martes."]
    assert rest == " Le espero"
    assert split_speakable("612 ") == ([], "612 ")
    assert split_speakable("Son 1.500 euros")[0] == []
    text = "¿Le va bien? Sí. Queda cerrado"
    units, rest = split_speakable(text)
    assert "".join(units) + rest == text


def _guard_under_test() -> tuple[object, list[object], list[tuple[str, dict]], ToolContext]:
    """A guard wired to a session that already knows one patient's data."""
    from pipecat.processors.frame_processor import FrameDirection

    from vortex.line.pipecat_voice import _LanguageState, _PrivacyGuard

    events: list[tuple[str, dict]] = []

    class Log:
        def event(self, kind: str, **kwargs: object) -> None:
            events.append((kind, kwargs))

    class Session:
        pass

    ctx = _ctx()
    ctx.log = Log()  # type: ignore[assignment]
    remember_patient(
        ctx,
        _patient(patient_id="P1", national_id="12345678Z", phone="612345678"),
    )
    Session.ctx = ctx
    state = _LanguageState()
    state.language = "es"
    guard = _PrivacyGuard(Session(), state)  # type: ignore[arg-type]

    pushed: list[object] = []

    async def capture(frame: object, direction: object = FrameDirection.DOWNSTREAM) -> None:
        pushed.append(frame)

    guard.push_frame = capture  # type: ignore[method-assign]
    return guard, pushed, events, ctx


async def test_privacy_guard_replaces_frame_and_logs() -> None:
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import TextFrame, TTSSpeakFrame
    from pipecat.processors.frame_processor import FrameDirection

    guard, pushed, events, ctx = _guard_under_test()

    safe = TextFrame("Buenos días, ¿en qué puedo ayudarle?")
    await guard.process_frame(safe, FrameDirection.DOWNSTREAM)
    assert [f.text for f in pushed] == ["Buenos días, ¿en qué puedo ayudarle?"]
    assert events == []

    leaky = TTSSpeakFrame("Su teléfono es 612 345 678")
    await guard.process_frame(leaky, FrameDirection.DOWNSTREAM)
    assert "612" not in leaky.text
    assert events and events[0][0] == "voice.privacy_block"
    assert events[0][1]["kinds"] == ["phone"]
    assert PATIENT_RECORDS_KEY in ctx.state


async def test_privacy_guard_scans_the_sentence_the_chunks_spell() -> None:
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import LLMFullResponseEndFrame, LLMTextFrame
    from pipecat.processors.frame_processor import FrameDirection

    from vortex.conversation.prompt import refusal_line_for

    guard, pushed, events, _ = _guard_under_test()

    for chunk in ("Su teléfono ", "es 612 ", "345 ", "678"):
        await guard.process_frame(LLMTextFrame(chunk), FrameDirection.DOWNSTREAM)
    assert pushed == []

    await guard.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
    spoken = "".join(getattr(f, "text", "") for f in pushed)
    assert "612" not in spoken
    assert spoken == refusal_line_for("es")
    assert events and events[0][0] == "voice.privacy_block"
    assert events[0][1]["kinds"] == ["phone"]


async def test_privacy_guard_forwards_clean_chunks_whole_and_in_order() -> None:
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import LLMFullResponseEndFrame, LLMTextFrame
    from pipecat.processors.frame_processor import FrameDirection

    guard, pushed, events, _ = _guard_under_test()

    chunks = ("Tiene ", "cita el martes ", "a las diez. ", "¿Le va bien", "?")
    for chunk in chunks:
        await guard.process_frame(LLMTextFrame(chunk), FrameDirection.DOWNSTREAM)
    await guard.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)

    assert "".join(getattr(f, "text", "") for f in pushed) == "".join(chunks)
    assert all(isinstance(f, LLMTextFrame) for f in pushed[:-1])
    assert events == []
