from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from vortex.observability.calllog import CallLog
from vortex.observability.replay import replay_call
from vortex.settings import REPO_ROOT

MADRID = ZoneInfo("Europe/Madrid")

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


# ---------------------------------------------------------------------------
# Cancellations demo — fills the Insights "Cancelaciones" panel
# ---------------------------------------------------------------------------


#: The pack file the "Replay cancellations" button drips into the live log —
#: one CallLog-shaped call per line, exactly like ``synthetic-data/logs/*``.
#: Regenerate with ``scripts/make_cancellation_pack.py``: the slot dates are
#: relative to generation time, so a stale file flips "pending" to "lost".
CANCELLATION_PACK = REPO_ROOT / "synthetic-data" / "logs" / "cancellation_demo.jsonl"


#: Five scripted callers free five slots spread across the week, then two more
#: book into two of those exact (provider, minute) pairs — which is precisely
#: what business_insights.cancellation_slots counts as "relocated". The other
#: three stay freed: two whose appointment day already passed ("lost") and one
#: still ahead ("pending"). Five freed slots also unlock the per-day chart.
async def write_cancellation_pack(path: Path, *, delay_s: float = 0.0) -> list[str]:
    """Write the demo batch to ``path`` — the synthetic-data pack file."""
    now = datetime.now(MADRID)

    def at(days: int, hour: int, minute: int = 0) -> datetime:
        return (now + timedelta(days=days)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )

    # caller, patient_id, insurer, appointment_id, provider_id, provider, slot
    cancellations = [
        ("Nadia Prats Vidal", "P00071", "sanitas", "APT-901", "PR01", "Dra. Ortiz", at(1, 10, 15)),
        ("Óscar Vidal Roca", "P00072", "mapfre", "APT-902", "PR02", "Dr. Sáez", at(-1, 12, 30)),
        ("Elena Marín Sola", "P00073", "asisa", "APT-903", "PR04", "Dra. Iglesias", at(4, 17)),
        ("Pau Bosch Llopis", "P00074", "sanitas", "APT-904", "PR02", "Dr. Sáez", at(-2, 9)),
        ("Sara Gil Martos", "P00075", "dkv", "APT-905", "PR01", "Dra. Ortiz", at(2, 11)),
    ]
    # Same provider and exact minute as two freed slots — the relocations.
    bookings = [
        ("Irene Soto Vila", "P00076", "sanitas", "PR01", "Dra. Ortiz", cancellations[0][6]),
        ("Luis Ferrer Cano", "P00077", "asisa", "PR01", "Dra. Ortiz", cancellations[4][6]),
    ]

    written: list[str] = []
    for i, (name, pid, insurer, aid, provider_id, provider, start) in enumerate(cancellations):
        written.append(
            await _cancel_call(
                path,
                f"demo-cancel-{i}-{int(time.time())}",
                name,
                pid,
                insurer,
                aid,
                provider_id,
                provider,
                start,
                delay_s,
            )
        )
    for i, (name, pid, insurer, provider_id, provider, start) in enumerate(bookings):
        written.append(
            await _book_into(
                path,
                f"demo-rebook-{i}-{int(time.time())}",
                name,
                pid,
                insurer,
                provider_id,
                provider,
                start,
                delay_s,
            )
        )
    return written


async def _cancel_call(
    path: Path,
    call_id: str,
    name: str,
    patient_id: str,
    insurer: str,
    appointment_id: str,
    provider_id: str,
    provider_name: str,
    start: datetime,
    delay_s: float,
) -> str:
    """One caller cancelling one appointment — the same tool chain a real
    cancel runs: identify, list the appointments, prepare, submit."""
    log = CallLog(call_id, path)
    log.event(
        "call.started",
        stream_sid=f"MZ-{call_id}",
        from_number="+34612345678",
        voice="demo",
        clinic="fake",
    )
    await asyncio.sleep(delay_s)
    await _turns(
        log,
        [
            ("assistant", "Clínica Arenal, buenos días. ¿En qué puedo ayudarle?"),
            ("user", f"Hola, quiero cancelar la cita que tengo con {provider_name}."),
            ("assistant", "Claro. ¿Me confirma su nombre completo?"),
            ("user", name),
        ],
        delay_s,
    )
    log.tool_called("find_patient", {"name": name})
    await asyncio.sleep(delay_s)
    given, *rest = name.split()
    log.tool_returned(
        "find_patient",
        {
            "status": "found",
            "patient": {
                "patient_id": patient_id,
                "given_name": given,
                "first_surname": rest[0] if rest else "",
                "second_surname": rest[1] if len(rest) > 1 else "",
                "insurer": insurer,
            },
        },
        39.0,
    )
    await asyncio.sleep(delay_s)
    log.tool_called("list_appointments", {"patient_id": patient_id, "when": "upcoming"})
    await asyncio.sleep(delay_s)
    log.tool_returned(
        "list_appointments",
        {
            "appointments": [
                {
                    "appointment_id": appointment_id,
                    "patient_id": patient_id,
                    "provider_id": provider_id,
                    "location_id": "centro",
                    "appointment_type_id": "review",
                    "start": start,
                    "duration_minutes": 15,
                    "status": "scheduled",
                    "provider": {"name": provider_name},
                }
            ]
        },
        44.0,
    )
    await asyncio.sleep(delay_s)
    await _turns(
        log,
        [
            (
                "assistant",
                f"Veo su cita con {provider_name} el {start.strftime('%d/%m')} "
                f"a las {start.strftime('%H:%M')}. ¿Se la cancelo?",
            ),
            ("user", "Sí, cancélemela por favor."),
            ("assistant", "Hecho, ya está cancelada. ¿Puedo ayudarle en algo más?"),
            ("user", "No, muchas gracias. Adiós."),
        ],
        delay_s,
    )
    log.tool_called("prepare_cancel", {"appointment_id": appointment_id, "patient_id": patient_id})
    await asyncio.sleep(delay_s)
    log.tool_returned(
        "prepare_cancel",
        {"action": {"kind": "cancel", "appointment_id": appointment_id}, "rejection": None},
        7.0,
    )
    await asyncio.sleep(delay_s)
    log.action_submitted(
        "/api/v1/submit/cancel",
        {"call_id": call_id, "appointment_id": appointment_id},
        {"status": "dry_run", "http_status": None, "detail": "demo"},
    )
    log.event("call.usage", **REFUSE_USAGE)
    log.event("call.ended", reason="hangup", media_frames_in=0, media_frames_out=0)
    log.summary(reason="hangup")
    return call_id


async def _book_into(
    path: Path,
    call_id: str,
    name: str,
    patient_id: str,
    insurer: str,
    provider_id: str,
    provider_name: str,
    start: datetime,
    delay_s: float,
) -> str:
    """One caller booking the exact (provider, minute) a cancellation freed —
    the relocation the panel counts."""
    log = CallLog(call_id, path)
    log.event(
        "call.started",
        stream_sid=f"MZ-{call_id}",
        from_number="+34612345679",
        voice="demo",
        clinic="fake",
    )
    await asyncio.sleep(delay_s)
    await _turns(
        log,
        [
            ("assistant", "Clínica Arenal, buenos días. ¿En qué puedo ayudarle?"),
            ("user", f"Quisiera pedir cita con {provider_name}, lo antes posible."),
            ("assistant", "Por supuesto. ¿Me dice su nombre completo?"),
            ("user", name),
        ],
        delay_s,
    )
    log.tool_called("find_patient", {"name": name})
    await asyncio.sleep(delay_s)
    given, *rest = name.split()
    log.tool_returned(
        "find_patient",
        {
            "status": "found",
            "patient": {
                "patient_id": patient_id,
                "given_name": given,
                "first_surname": rest[0] if rest else "",
                "second_surname": rest[1] if len(rest) > 1 else "",
                "insurer": insurer,
            },
        },
        36.0,
    )
    await asyncio.sleep(delay_s)
    log.tool_called(
        "check_eligibility",
        {"patient_id": patient_id, "specialty_id": "general_practice", "provider_id": provider_id},
    )
    await asyncio.sleep(delay_s)
    log.tool_returned("check_eligibility", {"allowed": True, "rejection": None}, 8.0)
    await asyncio.sleep(delay_s)
    log.tool_called(
        "find_slots",
        {
            "patient_id": patient_id,
            "provider_id": provider_id,
            "date_from": start.date().isoformat(),
            "date_to": start.date().isoformat(),
        },
    )
    await asyncio.sleep(delay_s)
    log.tool_returned(
        "find_slots",
        {
            "slots": [
                {
                    "start": start,
                    "provider_id": provider_id,
                    "location_id": "centro",
                    "appointment_type_id": "review",
                    "provider": {"name": provider_name},
                }
            ],
            "blocked": [],
        },
        52.0,
    )
    await asyncio.sleep(delay_s)
    await _turns(
        log,
        [
            (
                "assistant",
                f"Me queda un hueco con {provider_name} el {start.strftime('%d/%m')} "
                f"a las {start.strftime('%H:%M')}. ¿Se lo reservo?",
            ),
            ("user", "Sí, perfecto."),
            ("assistant", "Listo, ya tiene cita. Hasta luego."),
        ],
        delay_s,
    )
    log.tool_called(
        "prepare_booking",
        {
            "patient_id": patient_id,
            "slot": {"start": start.isoformat()},
            "policy_id": insurer,
        },
    )
    await asyncio.sleep(delay_s)
    book = {
        "kind": "book",
        "patient_id": patient_id,
        "provider_id": provider_id,
        "location_id": "centro",
        "appointment_type_id": "review",
        "slot": start.isoformat(),
        "policy_id": insurer,
    }
    log.tool_returned("prepare_booking", {"action": book, "rejection": None}, 6.0)
    await asyncio.sleep(delay_s)
    log.action_submitted(
        "/api/v1/submit/book",
        {"call_id": call_id, **{k: v for k, v in book.items() if k != "kind"}},
        {"status": "dry_run", "http_status": None, "detail": "demo"},
    )
    log.event("call.usage", **BOOK_USAGE)
    log.event("call.ended", reason="hangup", media_frames_in=0, media_frames_out=0)
    log.summary(reason="hangup")
    return call_id


async def write_cancellation_demo(path: Path, *, delay_s: float = 0.0) -> list[str]:
    """Deprecated name kept for callers that still generate straight into the
    log; the pack-file path is ``write_cancellation_pack`` + ``replay_cancellation_demo``."""
    return await write_cancellation_pack(path, delay_s=delay_s)


def load_cancellation_pack(pack_path: Path = CANCELLATION_PACK) -> list[list[dict]]:
    """Read the pack file and group its events into whole calls, file order."""
    grouped: dict[str, list[dict]] = {}
    for raw in pack_path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        grouped.setdefault(str(event.get("call_id") or ""), []).append(event)
    return list(grouped.values())


async def replay_cancellation_demo(
    log_path: Path,
    *,
    pack_path: Path = CANCELLATION_PACK,
    run_tag: str | None = None,
) -> list[str]:
    """Drip the pack's seven calls into the live log — fresh timestamps and
    fresh call_ids via ``replay_call``, so every replay lands inside the
    Insights window and repeated clicks never collide."""
    calls = load_cancellation_pack(pack_path)
    tag = run_tag or f"r{int(time.time())}"
    return [await replay_call(log_path, events, speed=0, run_tag=tag) for events in calls]
