"""Day-before confirmation calls: scripts, classification, store, worker, webhooks."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from vortex.contract import MADRID
from vortex.line.confirmation_calls import (
    ConfirmationCall,
    ConfirmationStore,
    ConfirmationWorker,
    DryRunCallsClient,
    ask_text,
    build_confirmation_call,
    call_language,
    cancel_confirmation_calls,
    classify_reply,
    ensure_confirmation_audio,
    handoff_from_parameters,
    handoff_ws_url,
    schedule_confirmation_call,
    twilio_locale,
    twiml_ask,
    twiml_handoff_to_agent,
    twiml_say,
    valid_audio_name,
)
from vortex.line.server import create_app

WHEN = datetime(2026, 9, 24, 16, 30, tzinfo=MADRID)
NOW = datetime(2026, 9, 20, 10, 0, tzinfo=MADRID)


def _pending(**over) -> ConfirmationCall:
    call = build_confirmation_call(
        to="+34662046392",
        when=WHEN,
        language="es",
        provider_name="Dra. Ortiz",
        location_name="Arenal Centro",
        now=NOW,
        lead=timedelta(hours=24),
        **over,
    )
    assert call is not None
    return call


# ---- language and script ---------------------------------------------------


def test_language_fallback_is_spanish() -> None:
    assert call_language("ca") == "ca"
    assert call_language("fr") == "es"
    assert call_language("") == "es"
    assert twilio_locale("eu") == "eu-ES"
    assert twilio_locale("en") == "en-US"
    assert twilio_locale("xx") == "es-ES"


def test_ask_text_spanish_full_stamp() -> None:
    text = ask_text(
        language="es", when=WHEN, provider_name="Dra. Ortiz", location_name="Arenal Centro"
    )
    assert "Dra. Ortiz" in text
    assert "Arenal Centro" in text
    assert "jueves 24 de septiembre a las 16:30" in text
    assert "¿Va a venir?" in text
    assert "la movemos ahora mismo" in text  # the in-call reschedule offer


def test_ask_text_other_languages_ask_the_same_question() -> None:
    for lang, marker, offer in (
        ("ca", "Hi vindrà?", "la movem ara"),
        ("gl", "Vai vir?", "movémola agora"),
        ("eu", "Etorriko al zara?", "mugituko dugu"),
        ("en", "Will you come?", "we'll change it right now"),
    ):
        text = ask_text(language=lang, when=WHEN)
        assert marker in text
        assert offer in text  # the in-call reschedule offer, in her language
        assert "24/09" in text  # digit stamp any voice can read


def test_twiml_escapes_and_routes() -> None:
    xml = twiml_ask(_pending(), "https://demo.example.com/")
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?><Response>')
    assert 'input="speech"' in xml
    assert 'language="es-ES"' in xml
    assert "/confirmation/result?cid=" in xml
    assert "/confirmation/noresult?cid=" in xml


# ---- classification --------------------------------------------------------


@pytest.mark.parametrize(
    ("transcript", "lang", "expected"),
    [
        ("Sí, claro, ahí estaré", "es", "confirmed"),
        ("vale vale", "es", "confirmed"),
        ("No puedo ir", "es", "not_coming"),
        ("No, mejor otro día", "es", "reschedule_requested"),
        ("Quiero cambiarla", "es", "reschedule_requested"),
        ("Sí, pero ¿puedo cambiarla?", "es", "reschedule_requested"),
        ("sí que aniré", "ca", "confirmed"),
        ("no puc venir", "ca", "not_coming"),
        ("vull canviar-la", "ca", "reschedule_requested"),
        ("si, vou", "gl", "confirmed"),
        ("non podo", "gl", "not_coming"),
        ("bai, etorriko naiz", "eu", "confirmed"),
        ("ez, ezin dut", "eu", "not_coming"),
        ("yes, I will be there", "en", "confirmed"),
        ("no, I can't make it", "en", "not_coming"),
        ("can we move it to another day", "en", "reschedule_requested"),
        ("marvellous weather", "es", "unknown"),
        ("", "es", "unknown"),
    ],
)
def test_classify_reply(transcript: str, lang: str, expected: str) -> None:
    assert classify_reply(transcript, lang) == expected


# ---- scheduling and store ----------------------------------------------------


def test_store_from_settings_is_shared_per_path(tmp_path: Path, monkeypatch) -> None:
    from vortex import settings as settings_module
    from vortex.line.confirmation_calls import confirmation_store_from_settings

    monkeypatch.setenv("VORTEX_CONFIRMATION_CALLS_PATH", str(tmp_path / "shared.json"))
    settings_module.reset_settings()
    try:
        settings = settings_module.get_settings()
        assert confirmation_store_from_settings(settings) is confirmation_store_from_settings(
            settings
        )
    finally:
        settings_module.reset_settings()


def test_build_skips_when_inside_lead_window() -> None:
    call = build_confirmation_call(
        to="+34662046392", when=WHEN, now=WHEN - timedelta(hours=12), lead=timedelta(hours=24)
    )
    assert call is None


def test_build_schedules_one_day_before() -> None:
    call = _pending()
    assert call.status == "pending"
    assert call.call_dt == WHEN - timedelta(days=1)
    assert call.language == "es"


def test_no_call_when_booked_within_24h() -> None:
    # Product rule: booked at 23:59 before the slot -> nothing goes out, even
    # with a tiny demo lead that would otherwise fire immediately.
    booked_just_now = WHEN - timedelta(hours=23, minutes=59)
    assert (
        build_confirmation_call(
            to="+34662046392",
            when=WHEN,
            now=booked_just_now,
            lead=timedelta(seconds=36),  # demo lead must not defeat the rule
        )
        is None
    )
    # One minute past the gap the call schedules normally.
    booked_day_before = WHEN - timedelta(hours=24, minutes=1)
    assert (
        build_confirmation_call(
            to="+34662046392", when=WHEN, now=booked_day_before, lead=timedelta(hours=24)
        )
        is not None
    )


def test_build_refuses_a_naive_datetime() -> None:
    with pytest.raises(ValueError, match="offset"):
        build_confirmation_call(to="+34662046392", when=datetime(2026, 9, 24, 16, 30), now=NOW)


@pytest.mark.asyncio
async def test_store_add_dedupes_pending(tmp_path: Path) -> None:
    store = ConfirmationStore(tmp_path / "calls.json")
    first = await schedule_confirmation_call(
        store, to="+34662046392", when=WHEN, now=NOW, lead=timedelta(hours=24)
    )
    second = await schedule_confirmation_call(
        store, to="+34662046392", when=WHEN, now=NOW, lead=timedelta(hours=24)
    )
    assert first is not None and second is not None
    rows = store._read()
    assert len(rows) == 1
    assert rows[0].confirmation_id == second.confirmation_id


@pytest.mark.asyncio
async def test_store_cancel_matching(tmp_path: Path) -> None:
    store = ConfirmationStore(tmp_path / "calls.json")
    await schedule_confirmation_call(
        store, to="+34662046392", when=WHEN, now=NOW, lead=timedelta(hours=24)
    )
    cancelled = await cancel_confirmation_calls(store, to="+34662046392", appointment_at=WHEN)
    assert cancelled == 1
    assert store._read()[0].status == "cancelled"


@pytest.mark.asyncio
async def test_claim_due_marks_a_bad_call_at_skipped_and_persists(tmp_path: Path) -> None:
    store = ConfirmationStore(tmp_path / "calls.json")
    call = _pending()
    await store.add(call)
    rows = store._read()
    rows[0].call_at = "not-a-datetime"
    store._write(rows)
    due = await store.claim_due(NOW)
    assert due == []
    persisted = store._read()
    assert persisted[0].status == "skipped"
    assert persisted[0].detail == "bad_call_at"


@pytest.mark.asyncio
async def test_claim_due_flips_once(tmp_path: Path) -> None:
    store = ConfirmationStore(tmp_path / "calls.json")
    call = _pending()
    await store.add(call)
    due = await store.claim_due(WHEN - timedelta(hours=23))
    assert [row.confirmation_id for row in due] == [call.confirmation_id]
    assert due[0].status == "calling"
    # Second poll: nothing left to claim, no double-dial.
    assert await store.claim_due(WHEN - timedelta(hours=23)) == []


# ---- worker ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_dry_run_marks_skipped(tmp_path: Path, offline_settings) -> None:
    store = ConfirmationStore(tmp_path / "calls.json")
    await store.add(_pending())
    worker = ConfirmationWorker(
        offline_settings, store=store, calls=DryRunCallsClient(), poll_secs=999
    )
    count = await worker.tick(WHEN - timedelta(hours=23))
    assert count == 1
    row = store._read()[0]
    assert row.status == "skipped"
    assert "not dialled" in row.detail


class _QueuedClient:
    def __init__(self) -> None:
        self.placed: list[str] = []

    async def place(self, *, to: str, twiml_url: str, status_callback_url: str):
        from vortex.line.confirmation_calls import CallResult

        self.placed.append(twiml_url)
        return CallResult(status="queued", detail="accepted by Twilio", sid="CA123")

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_worker_live_marks_calling_with_sid(tmp_path: Path, offline_settings) -> None:
    store = ConfirmationStore(tmp_path / "calls.json")
    call = _pending()
    await store.add(call)
    client = _QueuedClient()
    worker = ConfirmationWorker(offline_settings, store=store, calls=client, poll_secs=999)
    count = await worker.tick(WHEN - timedelta(hours=23))
    assert count == 1
    row = store._read()[0]
    assert row.status == "calling"
    assert row.twilio_call_sid == "CA123"
    assert f"cid={call.confirmation_id}" in client.placed[0]


# ---- webhooks ------------------------------------------------------------------


# ---- the wall's own voice for the Twilio-only segments -----------------------


def test_twiml_ask_plays_synthesised_audio_when_given_a_url() -> None:
    call = _pending()
    url = "https://demo.example.com/confirmation/audio/" + "a" * 24 + ".mp3"
    xml = twiml_ask(call, "https://demo.example.com", audio_url=url)
    assert f"<Play>{url}</Play>" in xml
    assert "<Say" not in xml


def test_twiml_ask_keeps_say_without_audio() -> None:
    xml = twiml_ask(_pending(), "https://demo.example.com")
    assert "<Say" in xml and "<Play>" not in xml


def test_handoff_plays_audio_then_connects() -> None:
    call = _pending()
    url = "https://demo.example.com/confirmation/audio/" + "b" * 24 + ".mp3"
    xml = twiml_handoff_to_agent(call, "wss://demo.example.com/ws", audio_url=url)
    assert f"<Play>{url}</Play>" in xml and "<Say" not in xml
    assert "<Connect><Stream" in xml


def test_twiml_say_plays_audio() -> None:
    url = "https://x/" + "c" * 24 + ".mp3"
    xml = twiml_say("Gracias, adiós.", "es", audio_url=url)
    assert f"<Play>{url}</Play>" in xml and "<Say" not in xml


@pytest.mark.asyncio
async def test_ensure_confirmation_audio_synthesises_and_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vortex import settings as settings_module
    from vortex.line import voice_config

    calls: list[str] = []

    def fake_synthesize(settings, cfg, text, *, language_code, voice_name) -> bytes:
        calls.append(f"{language_code}|{voice_name}")
        return b"fake-mp3"

    monkeypatch.setenv("VORTEX_CONFIRMATION_AUDIO_DIR", str(tmp_path / "audio"))
    monkeypatch.setenv("VORTEX_CALLS_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.setattr(voice_config, "synthesize", fake_synthesize)
    settings_module.reset_settings()
    try:
        settings = settings_module.get_settings()
        name = await ensure_confirmation_audio(settings, "Hola, le llamamos de la clínica.", "es")
        assert name is not None and valid_audio_name(name)
        assert (tmp_path / "audio" / name).read_bytes() == b"fake-mp3"
        assert calls == ["es-ES|es-ES-Chirp3-HD-Aoede"]
        # second render of the same line reuses the file, no new synthesis
        again = await ensure_confirmation_audio(settings, "Hola, le llamamos de la clínica.", "es")
        assert again == name
        assert len(calls) == 1
    finally:
        settings_module.reset_settings()


@pytest.mark.asyncio
async def test_ensure_confirmation_audio_returns_none_without_tts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vortex import settings as settings_module
    from vortex.line import voice_config

    def boom(settings, cfg, text, *, language_code, voice_name) -> bytes:
        raise RuntimeError("no credentials")

    monkeypatch.setenv("VORTEX_CONFIRMATION_AUDIO_DIR", str(tmp_path / "audio"))
    monkeypatch.setenv("VORTEX_CALLS_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.setattr(voice_config, "synthesize", boom)
    settings_module.reset_settings()
    try:
        settings = settings_module.get_settings()
        assert await ensure_confirmation_audio(settings, "Hola.", "es") is None
    finally:
        settings_module.reset_settings()


@pytest.fixture
def confirmation_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from vortex import settings as settings_module

    monkeypatch.setenv("VORTEX_VOICE_MODE", "stub")
    monkeypatch.setenv("VORTEX_CLINIC_MODE", "fake")
    monkeypatch.setenv("VORTEX_CALLS_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.setenv("VORTEX_CONFIRMATION_CALLS_PATH", str(tmp_path / "calls.json"))
    monkeypatch.setenv("VORTEX_PUBLIC_BASE_URL", "https://demo.example.com")
    settings_module.reset_settings()
    settings = settings_module.get_settings()
    client = TestClient(create_app(settings))
    yield client, settings
    settings_module.reset_settings()


def _seed(store_path: Path) -> ConfirmationCall:
    import asyncio

    store = ConfirmationStore(store_path)
    call = _pending()
    asyncio.run(store.add(call))
    asyncio.run(store.claim_due(WHEN - timedelta(hours=23)))  # -> calling
    return call


def test_twiml_endpoint_plays_the_wall_voice_when_tts_works(
    confirmation_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vortex.line import voice_config

    monkeypatch.setattr(voice_config, "synthesize", lambda settings, cfg, text, **kw: b"fake-mp3")
    client, settings = confirmation_client
    call = _seed(Path(settings.confirmation_calls_path))
    response = client.post(f"/confirmation/twiml?cid={call.confirmation_id}")
    assert response.status_code == 200
    assert "<Play>" in response.text and "<Say" not in response.text
    name = response.text.split("/confirmation/audio/")[1].split("</Play>")[0]
    audio = client.get(f"/confirmation/audio/{name}")
    assert audio.status_code == 200 and audio.content == b"fake-mp3"
    assert client.get("/confirmation/audio/not-a-hash.mp3").status_code == 404


def test_twiml_endpoint_serves_the_question(confirmation_client) -> None:
    client, settings = confirmation_client
    call = _seed(Path(settings.confirmation_calls_path))
    response = client.post(f"/confirmation/twiml?cid={call.confirmation_id}")
    assert response.status_code == 200
    assert 'input="speech"' in response.text
    assert "demo.example.com/confirmation/result" in response.text
    assert client.post("/confirmation/twiml?cid=nope").status_code == 404


def test_result_endpoint_records_confirmed(confirmation_client) -> None:
    client, settings = confirmation_client
    call = _seed(Path(settings.confirmation_calls_path))
    response = client.post(
        f"/confirmation/result?cid={call.confirmation_id}&attempt=1",
        content="SpeechResult=S%C3%AD%2C+ah%C3%AD+estar%C3%A9&Confidence=0.9",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    assert "cita confirmada" in response.text

    import asyncio

    store = ConfirmationStore(Path(settings.confirmation_calls_path))
    row = asyncio.run(store.get(call.confirmation_id))
    assert row is not None
    assert row.status == "confirmed"
    assert row.transcript == "Sí, ahí estaré"


def test_result_endpoint_reprompts_once_then_gives_up(confirmation_client) -> None:
    client, settings = confirmation_client
    call = _seed(Path(settings.confirmation_calls_path))
    first = client.post(
        f"/confirmation/result?cid={call.confirmation_id}&attempt=1",
        content="SpeechResult=blah+blah",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert "attempt=2" in first.text  # asks again

    second = client.post(
        f"/confirmation/result?cid={call.confirmation_id}&attempt=2",
        content="SpeechResult=blah+blah",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert "No se ha podido confirmar" in second.text

    import asyncio

    row = asyncio.run(
        ConfirmationStore(Path(settings.confirmation_calls_path)).get(call.confirmation_id)
    )
    assert row is not None
    assert row.status == "unclear"
    assert row.attempts == 2


def test_noresult_endpoint_marks_no_speech(confirmation_client) -> None:
    client, settings = confirmation_client
    call = _seed(Path(settings.confirmation_calls_path))
    response = client.post(f"/confirmation/noresult?cid={call.confirmation_id}")
    assert response.status_code == 200

    import asyncio

    row = asyncio.run(
        ConfirmationStore(Path(settings.confirmation_calls_path)).get(call.confirmation_id)
    )
    assert row is not None
    assert row.status == "unclear"
    assert row.detail == "no_speech"


def test_status_callback_marks_no_answer(confirmation_client) -> None:
    client, settings = confirmation_client
    call = _seed(Path(settings.confirmation_calls_path))
    response = client.post(
        f"/confirmation/status?cid={call.confirmation_id}",
        content="CallStatus=no-answer&CallSid=CA999",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 204

    import asyncio

    row = asyncio.run(
        ConfirmationStore(Path(settings.confirmation_calls_path)).get(call.confirmation_id)
    )
    assert row is not None
    assert row.status == "no_answer"
    assert row.twilio_call_sid == "CA999"


def test_status_callback_never_overwrites_an_answer(confirmation_client) -> None:
    client, settings = confirmation_client
    call = _seed(Path(settings.confirmation_calls_path))
    store = ConfirmationStore(Path(settings.confirmation_calls_path))

    import asyncio

    asyncio.run(store.update(call.confirmation_id, status="confirmed", transcript="sí"))
    # The completed callback arrives after the result webhook: it must not
    # stomp the recorded answer.
    client.post(
        f"/confirmation/status?cid={call.confirmation_id}",
        content="CallStatus=completed&CallSid=CA999",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    row = asyncio.run(store.get(call.confirmation_id))
    assert row is not None
    assert row.status == "confirmed"


# ---- the scheduler is generic: a second job rides the same machinery ----------


def test_a_second_job_registers_and_uses_its_own_policy() -> None:
    from vortex.line.confirmation_calls import CALL_JOBS, register_job

    class WaitlistOfferJob:
        job_id = "waitlist_offer_test"

        def call_at(self, *, when, lead):
            return when - timedelta(hours=2)  # its own schedule

        def ask_twiml(self, call, base_url, *, attempt, reprompt, audio_url=None):
            return "TWIML"

        def classify(self, transcript, language):
            return "confirmed"

        def ack(self, outcome, language):
            return "ack"

        def final_unclear(self, language):
            return "unclear"

        def no_speech(self, language):
            return "nospeech"

    register_job(WaitlistOfferJob())
    try:
        call = build_confirmation_call(
            to="+34662046392",
            when=WHEN,
            job="waitlist_offer_test",
            now=NOW,
            lead=timedelta(hours=2),
        )
        assert call is not None
        assert call.job == "waitlist_offer_test"
        assert call.call_dt == WHEN - timedelta(hours=2)
        job = CALL_JOBS[call.job]
        assert job.classify("whatever", "es") == "confirmed"
    finally:
        CALL_JOBS.pop("waitlist_offer_test", None)


# ---- in-call reschedule handoff -------------------------------------------------


def test_handoff_twiml_carries_the_context() -> None:
    call = _pending()
    xml = twiml_handoff_to_agent(call, "wss://demo.example.com/ws")
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert '<Connect><Stream url="wss://demo.example.com/ws">' in xml
    assert 'name="vortex_handoff" value="reschedule"' in xml
    assert f'value="{call.appointment_id}"' in xml
    assert f'value="{call.patient_id}"' in xml
    assert f'value="{call.language}"' in xml


def test_handoff_ws_url_switches_scheme() -> None:
    assert handoff_ws_url("https://demo.example.com/") == "wss://demo.example.com/ws"
    assert handoff_ws_url("http://localhost:8080") == "ws://localhost:8080/ws"


def test_handoff_from_parameters_roundtrip() -> None:
    params = {
        "vortex_handoff": "reschedule",
        "appointment_id": "apt-1",
        "patient_id": "pat-9",
        "language": "es",
    }
    handoff = handoff_from_parameters(params)
    assert handoff == {
        "kind": "reschedule",
        "appointment_id": "apt-1",
        "patient_id": "pat-9",
        "language": "es",
    }
    assert handoff_from_parameters({}) is None
    assert handoff_from_parameters({"vortex_handoff": "other"}) is None


def test_result_endpoint_hands_off_to_the_voice_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vortex import settings as settings_module

    monkeypatch.setenv("VORTEX_VOICE_MODE", "pipecat")
    monkeypatch.setenv("VORTEX_CLINIC_MODE", "fake")
    monkeypatch.setenv("VORTEX_CALLS_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.setenv("VORTEX_CONFIRMATION_CALLS_PATH", str(tmp_path / "calls.json"))
    monkeypatch.setenv("VORTEX_PUBLIC_BASE_URL", "https://demo.example.com")
    settings_module.reset_settings()
    settings = settings_module.get_settings()
    try:
        client = TestClient(create_app(settings))
        call = _seed(Path(settings.confirmation_calls_path))
        response = client.post(
            f"/confirmation/result?cid={call.confirmation_id}&attempt=1",
            content="SpeechResult=Quiero+cambiarla&Confidence=0.9",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 200
        assert '<Connect><Stream url="wss://demo.example.com/ws">' in response.text
        assert 'name="vortex_handoff" value="reschedule"' in response.text
        assert "Le paso con mi compañero" in response.text

        import asyncio

        row = asyncio.run(
            ConfirmationStore(Path(settings.confirmation_calls_path)).get(call.confirmation_id)
        )
        assert row is not None
        assert row.status == "reschedule_requested"
        assert row.detail == "handoff_to_voice_agent"
    finally:
        settings_module.reset_settings()


def test_result_endpoint_stub_voice_keeps_the_callback_promise(confirmation_client) -> None:
    client, settings = confirmation_client
    call = _seed(Path(settings.confirmation_calls_path))
    response = client.post(
        f"/confirmation/result?cid={call.confirmation_id}&attempt=1",
        content="SpeechResult=Quiero+cambiarla&Confidence=0.9",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    assert "<Connect>" not in response.text
    assert "para mover la cita" in response.text

    import asyncio

    row = asyncio.run(
        ConfirmationStore(Path(settings.confirmation_calls_path)).get(call.confirmation_id)
    )
    assert row is not None
    assert row.status == "reschedule_requested"
    assert row.detail == "answered"


def test_handoff_note_enters_the_prompt() -> None:
    from vortex.conversation.prompt import build_system_prompt, handoff_note_for

    handoff = {
        "kind": "reschedule",
        "appointment_id": "apt-1",
        "patient_id": "pat-9",
        "language": "es",
    }
    note = handoff_note_for(handoff)
    assert "apt-1" in note and "pat-9" in note and "Spanish" in note
    prompt = build_system_prompt(WHEN, handoff=handoff)
    assert "HANDOFF" in prompt and "apt-1" in prompt
    # the transferred patient is never re-identified on the same call
    assert "ALREADY IDENTIFIED" in prompt
    assert "pat-9" in prompt
    assert handoff_note_for(None) == ""


def test_handoff_greeting_is_mid_task_and_localised() -> None:
    from vortex.conversation.prompt import handoff_greeting_for

    assert "compañero que le agenda las citas" in handoff_greeting_for("es")
    assert "colleague who books your appointments" in handoff_greeting_for("en")
    assert handoff_greeting_for("fr") == handoff_greeting_for("en")


def test_session_open_picks_up_the_handoff(tmp_path: Path, offline_settings) -> None:
    from vortex.line.session import CallSession
    from vortex.line.twilio import StartPayload

    start = StartPayload(
        streamSid="MZ-1",
        callSid="CA-handoff",
        customParameters={
            "vortex_handoff": "reschedule",
            "appointment_id": "apt-1",
            "patient_id": "pat-9",
            "language": "es",
        },
    )
    session = CallSession.open(start, settings=offline_settings, now=WHEN)
    assert session.handoff is not None
    assert session.handoff["appointment_id"] == "apt-1"
    assert session.language == "es"

    plain = CallSession.open(
        StartPayload(streamSid="MZ-2", callSid="CA-plain", customParameters={}),
        settings=offline_settings,
        now=WHEN,
    )
    assert plain.handoff is None
