from __future__ import annotations

import asyncio
import time
from pathlib import Path

from vortex.observability.calllog import CallLog

BOOK_TURNS = [
    ("assistant", "Clínica Arenal, buenos días. ¿En qué puedo ayudarle?"),
    ("user", "Quiero una revisión con la doctora Ortiz, por la mañana."),
    ("assistant", "Claro. ¿Me confirma su nombre y fecha de nacimiento?"),
    ("user", "Marta Ruiz López, doce de marzo de mil novecientos ochenta y cinco."),
    ("assistant", "La tengo. Dra. Ortiz, Arenal Centro, mañana a las 10:15. ¿Se la reservo?"),
    ("user", "Sí, perfecto."),
    ("assistant", "Listo. Revisión mañana a las 10:15 con la Dra. Ortiz en Centro. Hasta luego."),
]

#: What the providers metered on a scripted call. The same shape the line lane
#: writes for a real one, so every page shows a cost without a live call.
#: The refusal leans on two Google TTS services on purpose: the Gemini voice
#: has no published per-character price, which is what a *partial* call looks
#: like on screen.
BOOK_USAGE: dict[str, object] = {
    "metered": True,
    "stt": {"provider": "soniox", "model": "stt-rt-v5", "audio_seconds": 47.3, "requests": 12},
    "llm": {
        "provider": "helmcode",
        "model": "deepseek-v4-flash",
        "prompt_tokens": 11840,
        "completion_tokens": 512,
        "reasoning_tokens": 0,
        "cache_read_input_tokens": 0,
        "requests": 7,
    },
    "tts": [
        {
            "provider": "google",
            "service": "GoogleHttpTTSService",
            "model": "es-ES-Chirp3-HD-Aoede",
            "characters": 1180,
            "requests": 6,
        }
    ],
}

REFUSE_USAGE: dict[str, object] = {
    "metered": True,
    "stt": {"provider": "soniox", "model": "stt-rt-v5", "audio_seconds": 21.6, "requests": 6},
    "llm": {
        "provider": "helmcode",
        "model": "deepseek-v4-flash",
        "prompt_tokens": 6420,
        "completion_tokens": 214,
        "reasoning_tokens": 0,
        "cache_read_input_tokens": 0,
        "requests": 3,
    },
    "tts": [
        {
            "provider": "google",
            "service": "GoogleHttpTTSService",
            "model": "es-ES-Chirp3-HD-Aoede",
            "characters": 226,
            "requests": 3,
        },
        {
            "provider": "google",
            "service": "GeminiTTSService",
            "model": "gemini-2.5-flash-tts",
            "characters": 90,
            "requests": 1,
        },
    ],
}

REFUSE_TURNS = [
    ("assistant", "Clínica Arenal, buenos días. ¿En qué puedo ayudarle?"),
    ("user", "Necesito cita de cardiología para mi padre, tiene DKV."),
    ("assistant", "Cardiología con DKV no está cubierta en esta clínica. No puedo agendarla."),
]


async def write_scripted_call(
    path: Path,
    *,
    scenario: str = "book",
    delay_s: float = 0.35,
) -> str:
    call_id = f"demo-{scenario}-{int(time.time())}"
    log = CallLog(call_id, path)
    log.event(
        "call.started",
        stream_sid=f"MZ-{call_id}",
        from_number="+34612345678",
        voice="demo",
        clinic="fake",
    )
    await asyncio.sleep(delay_s)

    if scenario == "refuse":
        await _turns(log, REFUSE_TURNS[:2], delay_s)
        log.tool_called(
            "find_patient",
            {"name": "padre", "national_id": None, "phone": "+34612345678"},
        )
        await asyncio.sleep(delay_s)
        log.tool_returned(
            "find_patient",
            {
                "status": "found",
                "patient": {
                    "patient_id": "P00011",
                    "given_name": "Andrés",
                    "first_surname": "Ruiz",
                    "second_surname": "",
                    "insurer": "dkv",
                },
            },
            38.0,
        )
        await asyncio.sleep(delay_s)
        log.tool_called("check_eligibility", {"patient_id": "P00011", "specialty_id": "cardiology"})
        await asyncio.sleep(delay_s)
        log.tool_returned(
            "check_eligibility",
            {
                "allowed": False,
                "rejection": {
                    "reason": "specialty_not_covered",
                    "detail": "DKV does not cover cardiology at Arenal",
                },
            },
            12.0,
        )
        await asyncio.sleep(delay_s)
        log.assistant_turn(REFUSE_TURNS[2][1])
        await asyncio.sleep(delay_s)
        payload = {"call_id": call_id, "reason": "specialty_not_covered"}
        log.action_submitted(
            "/api/v1/submit/no-action",
            payload,
            {"status": "dry_run", "http_status": None, "detail": "demo"},
        )
        log.event("call.usage", **REFUSE_USAGE)
        log.event("call.ended", reason="hangup", media_frames_in=0, media_frames_out=0)
        log.summary(reason="hangup")
        return call_id

    await _turns(log, BOOK_TURNS[:2], delay_s)
    log.tool_called("find_patient", {"name": "Marta Ruiz López"})
    await asyncio.sleep(delay_s)
    log.tool_returned(
        "find_patient",
        {
            "status": "found",
            "patient": {
                "patient_id": "P00042",
                "given_name": "Marta",
                "first_surname": "Ruiz",
                "second_surname": "López",
                "insurer": "sanitas",
                "date_of_birth": "1985-03-12",
            },
        },
        41.0,
    )
    await asyncio.sleep(delay_s)
    await _turns(log, BOOK_TURNS[2:4], delay_s)
    log.tool_called(
        "check_eligibility",
        {"patient_id": "P00042", "specialty_id": "general_practice", "provider_id": "PR01"},
    )
    await asyncio.sleep(delay_s)
    log.tool_returned("check_eligibility", {"allowed": True, "rejection": None}, 9.0)
    await asyncio.sleep(delay_s)
    log.tool_called(
        "find_slots",
        {
            "patient_id": "P00042",
            "provider_id": "PR01",
            "date_from": "2026-09-19",
            "date_to": "2026-09-19",
            "time_from": "00:00:00",
            "time_to": "14:00:00",
        },
    )
    await asyncio.sleep(delay_s)
    log.tool_returned(
        "find_slots",
        {
            "slots": [
                {
                    "start": "2026-09-19T10:15:00+02:00",
                    "provider_id": "PR01",
                    "location_id": "centro",
                    "appointment_type_id": "review",
                    "provider": {"name": "Dra. Ortiz"},
                }
            ],
            "blocked": [],
            "appointment_type": {"appointment_type_id": "review", "name": "Review"},
        },
        55.0,
    )
    await asyncio.sleep(delay_s)
    await _turns(log, BOOK_TURNS[4:6], delay_s)
    log.tool_called(
        "prepare_booking",
        {
            "patient_id": "P00042",
            "slot": {"start": "2026-09-19T10:15:00+02:00"},
            "policy_id": "sanitas",
        },
    )
    await asyncio.sleep(delay_s)
    book = {
        "kind": "book",
        "patient_id": "P00042",
        "provider_id": "PR01",
        "location_id": "centro",
        "appointment_type_id": "review",
        "slot": "2026-09-19T10:15:00+02:00",
        "policy_id": "sanitas",
    }
    log.tool_returned("prepare_booking", {"action": book, "rejection": None}, 6.0)
    await asyncio.sleep(delay_s)
    log.action_submitted(
        "/api/v1/submit/book",
        {"call_id": call_id, **{k: v for k, v in book.items() if k != "kind"}},
        {"status": "dry_run", "http_status": None, "detail": "demo"},
    )
    await asyncio.sleep(delay_s)
    log.assistant_turn(BOOK_TURNS[6][1])
    log.event("call.usage", **BOOK_USAGE)
    log.event("call.ended", reason="hangup", media_frames_in=0, media_frames_out=0)
    log.summary(reason="hangup")
    return call_id


async def _turns(log: CallLog, turns: list[tuple[str, str]], delay_s: float) -> None:
    for role, text in turns:
        if role == "user":
            log.user_turn(text)
        else:
            log.assistant_turn(text)
        await asyncio.sleep(delay_s)
