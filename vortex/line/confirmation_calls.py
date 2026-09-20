"""Outbound scheduled calls: a small generic scheduler plus its first job.

``ConfirmationCall`` is the generic row (one per scheduled outbound call, with
a ``job`` naming what the call is for), ``ConfirmationStore`` the shared JSON
queue, and ``ConfirmationWorker`` the one loop that dials whatever is due.
``server.py``'s ``/confirmation/*`` routes are the system's single webhook
surface: every job's TwiML, Gather result, silence and terminal status flow
through them and dispatch on the row's ``job``.

A new scheduled-call job (waitlist offers, pre-op instructions, ...) registers
a ``CallJob`` with its own texts, answer classification and scheduling policy;
the queue, worker, routes and outcome bookkeeping come with the system.

The first job is ``appointment_confirmation``: the day before an accepted
booking we call the patient, say the appointment in their language and ask
whether they will come; the answer (yes / no / wants to reschedule) is stored
per appointment. ``motivo`` (``KNOWN_MOTIVOS``) rides the same job and the
same yes/no flow but opens with a different clause — confirmación, a plain
recordatorio, a reprogramación the clinic initiates, a seguimiento, or
``call_now`` to jump the queue (see ``build_confirmation_call``).

``VORTEX_CONFIRMATION_CALLS`` gates this entire module, not just the
appointment-confirmation job: with it off, ``server.py`` never starts
``ConfirmationWorker`` and ``session.py`` never queues a row, whatever the
row's ``job`` or ``motivo`` would have been. One flag, one subsystem.

The worker itself does not care whether a socket is open: ``server.py``
starts it once in the FastAPI app's own lifespan (``_app_lifespan``), the
same place the SMS ``ReminderWorker`` starts, so it polls and dials on its
own schedule for as long as the process is up — an inbound call queues a
row, it never has to be the thing that drives the worker's next tick.

--- the original confirmation-call notes ---

Day-before confirmation calls for accepted bookings.

When a book is accepted we queue a voice call for ``slot - lead`` (default one
day). A small background worker drains due rows and calls the patient through
Twilio: the call says tomorrow's appointment in the patient's language and asks
whether they will come. The answer (yes / no / wants to reschedule) lands back
on our TwiML webhooks and is stored per appointment, so the clinic can act on
it and the dashboard can count it.

The TwiML is served by this same server (``/confirmation/*`` routes in
``vortex/line/server.py``) and needs only Twilio: no STT/LLM/TTS keys, because
``Gather input="speech"`` transcribes the answer on Twilio's side. That is also
why the flow is a fixed question with a small per-language keyword classifier
instead of the LLM receptionist.

Future hooks, by design:
- ``not_coming`` -> offer the freed slot to a waitlist (the status is stored;
  a waitlist worker can subscribe to it).
- ``no_answer`` / ``unclear`` -> retry policy or SMS fallback (``call_at`` and
  ``attempts`` are on the row for exactly that).

Persistence is a JSON file next to the calls log, mirroring
``vortex/line/sms_reminders.py``. Failures never touch the submit path.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import unicodedata
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol
from xml.sax.saxutils import escape, quoteattr

import httpx

from vortex.contract import MADRID
from vortex.conversation.prompt import CLINIC_NAME
from vortex.line import voice_config
from vortex.line.sms import format_slot_es
from vortex.settings import REPO_ROOT, Settings

log = logging.getLogger("vortex.line.confirmation_calls")

TWILIO_CALLS_URL = "https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls.json"

CALL_BUDGET_SECS = 8.0

#: Product rule (Cristina, 2026-09-19): an appointment booked less than 24 h
#: before its slot gets no confirmation call at all - the patient just booked
#: it, there is nothing to remind. Hard-coded, not the lead: the lead is a demo
#: knob, this rule is not.
MIN_BOOKING_GAP = timedelta(hours=24)

#: Why this particular outbound call is happening — a lighter, business-
#: facing label than ``job`` (which selects the TwiML/classification code
#: path; today only ``appointment_confirmation`` exists). Every motivo below
#: rides the *same* job and the *same* yes/no flow: only the opening clause
#: (``_MOTIVO_OPENING``) changes, e.g. "para confirmar su cita" vs. "para
#: recordarle su cita". A motivo that genuinely needs a different question or
#: a different answer classification is not a new motivo, it is a new
#: ``CallJob`` (see ``register_job``) — this list only changes what the call
#: opens by saying, never what it asks or how it reads the reply.
#:
#: Deliberately not a closed set: ``motivo`` is a plain ``str`` on
#: ``ConfirmationCall`` and nothing validates membership, so a caller can use
#: a value not listed here (it opens with the ``"confirmacion"`` clause as a
#: safe default — see ``ask_text``). ``KNOWN_MOTIVOS`` documents the ones the
#: product actually asked for; add to it, do not gate on it.
KNOWN_MOTIVOS: tuple[str, ...] = (
    "confirmacion",  # day-before "will you come" — the original, still the default
    "recordatorio",  # a plain reminder, no explicit yes/no framing
    "reprogramacion",  # the clinic needs to move this appointment
    "seguimiento",  # a follow-up call about a past or upcoming visit
    "call_now",  # place it on the very next worker tick — see build_confirmation_call
)
DEFAULT_MOTIVO = "confirmacion"

#: The job a cancellation (phone or wall) queues, always with
#: ``motivo="call_now"`` — see ``queue_cancellation_rebooking_call`` and
#: ``CancellationRebookingJob``. A plain string, not an enum member: every
#: other job id on ``ConfirmationCall.job`` is one too.
CANCELLATION_REBOOKING_JOB = "cancellation_rebooking"

ConfirmationStatus = Literal[
    "pending",  # queued, call_at in the future
    "calling",  # claimed by the worker / Twilio accepted the call
    "confirmed",  # patient said yes
    "not_coming",  # patient said no
    "reschedule_requested",  # patient wants to move it; the call hands off to the agent
    "no_answer",  # terminal Twilio status: no-answer / busy
    "unclear",  # answered but no usable reply (silence, hangup, unintelligible)
    "failed",  # Twilio rejected or the call failed
    "cancelled",  # the appointment was cancelled before we called
    "skipped",  # deliberately not placed (dry run, bad row)
]

CallOutcome = Literal["confirmed", "not_coming", "reschedule_requested", "unknown"]

#: Languages the confirmation call speaks, as (Twilio <Say>/<Gather> locale).
#: Anything else falls back to Spanish, the clinic's default on this track.
TWILIO_LOCALES: dict[str, str] = {
    "es": "es-ES",
    "ca": "ca-ES",
    "gl": "gl-ES",
    "eu": "eu-ES",
    "en": "en-US",
}
DEFAULT_CALL_LANGUAGE = "es"


def twilio_locale(language: str | None) -> str:
    return TWILIO_LOCALES.get(
        (language or "").strip().lower(), TWILIO_LOCALES[DEFAULT_CALL_LANGUAGE]
    )


def call_language(language: str | None) -> str:
    """The ISO-639-1 code this call runs in. Unknown/empty -> Spanish."""
    code = (language or "").strip().lower()
    return code if code in TWILIO_LOCALES else DEFAULT_CALL_LANGUAGE


def _fold(text: str) -> str:
    """lowercase + strip accents so ``sí``/``si``/``Sí`` all match."""
    flat = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in flat if not unicodedata.combining(ch))


# Order matters: reschedule is checked first (a "no, mejor otro día" is a move,
# not a plain refusal), then no, then yes.
_RESCHEDULE: dict[str, tuple[str, ...]] = {
    "es": (
        "cambia*",
        "cambio",
        "mover",
        "mueve",
        "reagendar",
        "reprogramar",
        "aplazar",
        "posponer",
        "otro dia",
        "otra hora",
    ),
    "ca": ("canvi*", "mour", "reprogramar", "ajornar", "altre dia", "altra hora"),
    "gl": ("cambia*", "cambio", "muda*", "reprogramar", "aprazar", "outro dia", "outra hora"),
    "eu": ("aldatu", "atzeratu", "beste egun", "beste ordu"),
    "en": (
        "reschedule",
        "change",
        "move",
        "postpone",
        "another day",
        "another time",
        "different day",
    ),
}
_NO: dict[str, tuple[str, ...]] = {
    "es": ("no", "no puedo", "no voy", "no ire", "imposible", "cancelar", "cancela"),
    "ca": ("no", "no puc", "no vaig", "impossible", "cancelar", "anular"),
    "gl": ("non", "non podo", "non vou", "imposible", "cancelar", "anular"),
    "eu": ("ez", "ez dut", "ezeztatu"),
    "en": ("no", "can't", "cant", "cannot", "won't", "wont", "cancel"),
}
_YES: dict[str, tuple[str, ...]] = {
    "es": (
        "si",
        "claro",
        "vale",
        "confirmo",
        "voy",
        "ire",
        "ahi estare",
        "por supuesto",
        "correcto",
        "de acuerdo",
    ),
    "ca": ("si", "clar", "val", "confirmo", "vaig", "anire", "d'acord"),
    "gl": ("si", "claro", "vaia", "confirmo", "vou", "irei", "de acordo"),
    "eu": ("bai", "noski", "berresten", "etorriko", "ondo"),
    "en": ("yes", "yeah", "yep", "sure", "confirm", "i will", "i'll be there", "of course"),
}


def _matches(folded: str, words: tuple[str, ...]) -> bool:
    # ``stem*`` matches any continuation (``cambia*`` catches ``cambiarla``);
    # a plain word needs full boundaries so ``si`` does not fire on ``sitio``.
    for w in words:
        if w.endswith("*"):
            if re.search(rf"(?<!\w){re.escape(w[:-1])}", folded):
                return True
        elif re.search(rf"(?<!\w){re.escape(w)}(?!\w)", folded):
            return True
    return False


def classify_reply(transcript: str, language: str | None = None) -> CallOutcome:
    """Keyword classification of the patient's spoken answer.

    Fixed-question flow, so a tiny per-language word list beats dragging the
    LLM onto a phone line for a yes/no. ``unknown`` lets the caller retry once.
    """
    folded = _fold(transcript)
    if not folded.strip():
        return "unknown"
    lang = call_language(language)
    if _matches(folded, _RESCHEDULE[lang]):
        return "reschedule_requested"
    if _matches(folded, _NO[lang]):
        return "not_coming"
    if _matches(folded, _YES[lang]):
        return "confirmed"
    return "unknown"


def _stamp_for(language: str, when: datetime) -> str:
    """Appointment wording inside the call. Spanish gets the full SMS phrasing;
    the other languages take digits, which any Twilio voice reads cleanly."""
    if language == "es":
        return format_slot_es(when)
    local = when.astimezone(MADRID)
    return f"{local.day:02d}/{local.month:02d} {local.strftime('%H:%M')}"


def _named(provider_name: str, location_name: str) -> tuple[str, str]:
    return provider_name.strip(), location_name.strip()


#: The opening clause naming *why* we are calling, per language and motivo —
#: the only piece of ``_ASK`` that varies with ``motivo``. An unknown motivo
#: (or ``call_now``, which is about *when* to dial, not what to say) falls
#: back to the ``"confirmacion"`` clause: see ``ask_text``.
_MOTIVO_OPENING: dict[str, dict[str, str]] = {
    "es": {
        "confirmacion": "para confirmar su cita",
        "recordatorio": "para recordarle su cita",
        "reprogramacion": "porque necesitamos reprogramar su cita",
        "seguimiento": "para hacer un seguimiento de su cita",
    },
    "ca": {
        "confirmacion": "per confirmar la seva cita",
        "recordatorio": "per recordar-li la seva cita",
        "reprogramacion": "perquè necessitem reprogramar la seva cita",
        "seguimiento": "per fer un seguiment de la seva cita",
    },
    "gl": {
        "confirmacion": "para confirmar a súa cita",
        "recordatorio": "para lembrarlle a súa cita",
        "reprogramacion": "porque necesitamos reprogramar a súa cita",
        "seguimiento": "para facer un seguimento da súa cita",
    },
    "eu": {
        "confirmacion": "hitzordua berresteko",
        "recordatorio": "hitzordua gogorarazteko",
        "reprogramacion": "hitzordua berrantolatu behar dugulako",
        "seguimiento": "hitzorduaren jarraipena egiteko",
    },
    "en": {
        "confirmacion": "to confirm your appointment",
        "recordatorio": "to remind you of your appointment",
        "reprogramacion": "because we need to reschedule your appointment",
        "seguimiento": "to follow up on your appointment",
    },
}


def _motivo_clause(lang: str, motivo: str) -> str:
    by_motivo = _MOTIVO_OPENING[lang]
    return by_motivo.get(motivo, by_motivo[DEFAULT_MOTIVO])


_ASK = {
    "es": (
        "Hola, le llamamos de {clinic} {motivo_clause}. "
        "Mañana tiene cita{with_whom}: {stamp}. "
        "¿Va a venir? Diga sí para confirmar. Si prefiere cambiarla, dígamelo y la movemos "
        "ahora mismo. Si no puede venir, diga no."
    ),
    "ca": (
        "Hola, li truquem de {clinic} {motivo_clause}, demà{with_whom}: {stamp}. "
        "Hi vindrà? Digui sí per confirmar. Si prefereix canviar-la, m'ho diu i la movem ara "
        "mateix. Si no hi pot venir, digui no."
    ),
    "gl": (
        "Hola, chamámoslle de {clinic} {motivo_clause}, mañá{with_whom}: {stamp}. "
        "Vai vir? Diga si para confirmar. Se prefire cambiala, dígamo e movémola agora mesmo. "
        "Se non pode vir, diga non."
    ),
    "eu": (
        "Kaixo, {clinic} koak gara, {motivo_clause} deitzen dizugu, "
        "bihar duzun hitzordua{with_whom}: {stamp}. "
        "Etorriko al zara? Esan bai berresteko. Aldatzea nahiago baduzu, esadazu eta oraintxe "
        "bertan mugituko dugu. Ezin bazara etorri, esan ez."
    ),
    "en": (
        "Hello, this is {clinic} calling {motivo_clause} tomorrow{with_whom}: {stamp}. "
        "Will you come? Say yes to confirm. If you'd rather move it, tell me and we'll change "
        "it right now. If you can't make it, say no."
    ),
}
_WITH_WHOM = {
    "es": " con {provider} en {location}",
    "ca": " amb {provider} a {location}",
    "gl": " con {provider} en {location}",
    "eu": " {provider} gurekin, {location} lekuan",
    "en": " with {provider} at {location}",
}
_ACK: dict[str, dict[CallOutcome, str]] = {
    "es": {
        "confirmed": "Perfecto, cita confirmada. Le esperamos mañana. Gracias, adiós.",
        "not_coming": (
            "De acuerdo, anotamos que no puede venir. "
            "La clínica podrá ofrecer ese hueco a otra persona. Gracias, adiós."
        ),
        "reschedule_requested": (
            "De acuerdo. La clínica se pondrá en contacto con usted para mover la cita. "
            "Gracias, adiós."
        ),
        "unknown": "Perdone, no le he entendido. ¿Va a venir mañana a su cita? Diga sí o no.",
    },
    "ca": {
        "confirmed": "Perfecte, cita confirmada. L'esperem demà. Gràcies, adéu.",
        "not_coming": "D'acord, anotem que no hi pot venir. Gràcies, adéu.",
        "reschedule_requested": "D'acord. La clínica el trucarà per moure la cita. Gràcies, adéu.",
        "unknown": "Perdoni, no l'he entès. Vindrà demà a la seva cita? Digui sí o no.",
    },
    "gl": {
        "confirmed": "Perfecto, cita confirmada. Esperámoslle mañá. Grazas, adeus.",
        "not_coming": "De acordo, anotamos que non pode vir. Grazas, adeus.",
        "reschedule_requested": "De acordo. A clínica chamará para mover a cita. Grazas, adeus.",
        "unknown": "Perdone, non o entendín. Vai vir mañá á súa cita? Diga si ou non.",
    },
    "eu": {
        "confirmed": "Primeran, hitzordua berretsita. Zure zain, bihar. Eskerrik asko, agur.",
        "not_coming": "Ondo, ohartarazten dugu ez zarela etorriko. Eskerrik asko, agur.",
        "reschedule_requested": (
            "Ondo. Klinikak deituko dizu hitzordua mugitzeko. Eskerrik asko, agur."
        ),
        "unknown": "Barkatu, ez zaitut ulertu. Etorriko al zara bihar? Esan bai edo ez.",
    },
    "en": {
        "confirmed": "Perfect, your appointment is confirmed. See you tomorrow. Goodbye.",
        "not_coming": "Understood, we've noted you can't come. Thank you, goodbye.",
        "reschedule_requested": (
            "Understood. The clinic will call you to move the appointment. Thank you, goodbye."
        ),
        "unknown": (
            "Sorry, I didn't catch that. Will you come to your appointment tomorrow? Say yes or no."
        ),
    },
}
_FINAL_UNCLEAR = {
    "es": "No se ha podido confirmar. La clínica se pondrá en contacto con usted. Gracias, adiós.",
    "ca": "No s'ha pogut confirmar. La clínica es posarà en contacte amb vostè. Gràcies, adéu.",
    "gl": "Non se puido confirmar. A clínica porase en contacto con vostede. Grazas, adeus.",
    "eu": "Ezin izan da berretsi. Klinikak jarriko da zurekin harremanetan. Eskerrik asko, agur.",
    "en": "We couldn't confirm. The clinic will get in touch with you. Thank you, goodbye.",
}


def final_unclear_text(language: str) -> str:
    return _FINAL_UNCLEAR[call_language(language)]


_NO_SPEECH = {
    "es": "No hemos oído su respuesta. Su cita queda pendiente de confirmar. Gracias, adiós.",
    "ca": "No hem sentit la seva resposta. La cita queda pendent de confirmar. Gràcies, adéu.",
    "gl": "Non oímos a súa resposta. A cita queda pendente de confirmar. Grazas, adeus.",
    "eu": (
        "Ez dugu zure erantzuna entzun. Hitzordua berretsi gabe geratzen da. Eskerrik asko, agur."
    ),
    "en": "We didn't hear your answer. Your appointment stays unconfirmed. Thank you, goodbye.",
}


def _with_whom_clause(lang: str, provider_name: str, location_name: str) -> str:
    """The "con Dra. X en Sitio Y" (or just "con Dra. X") clause, in one
    language — shared between the day-before ask and the cancellation
    rebooking ask, since both name the same doctor/site fact."""
    provider, location = _named(provider_name, location_name)
    if provider and location:
        return _WITH_WHOM[lang].format(provider=provider, location=location)
    if provider and lang in ("es", "gl", "en"):
        return {"es": " con {p}", "gl": " con {p}", "en": " with {p}"}[lang].format(p=provider)
    return ""


def ask_text(
    *,
    language: str,
    when: datetime,
    provider_name: str = "",
    location_name: str = "",
    clinic_name: str = CLINIC_NAME,
    motivo: str = DEFAULT_MOTIVO,
) -> str:
    lang = call_language(language)
    return _ASK[lang].format(
        clinic=clinic_name,
        with_whom=_with_whom_clause(lang, provider_name, location_name),
        stamp=_stamp_for(lang, when),
        motivo_clause=_motivo_clause(lang, motivo),
    )


def ack_text(outcome: CallOutcome, language: str) -> str:
    return _ACK[call_language(language)][outcome]


def no_speech_text(language: str) -> str:
    return _NO_SPEECH[call_language(language)]


def _gather(
    action_url: str, locale: str, say: str, *, timeout: int = 10, audio_url: str | None = None
) -> str:
    return (
        f'<Gather input="speech" language="{locale}" action={quoteattr(action_url)} '
        f'method="POST" speechTimeout="auto" timeout="{timeout}">'
        + _speech(locale, say, audio_url)
        + "</Gather>"
    )


# --- In-call reschedule handoff -------------------------------------------
# When the patient asks to move the appointment, the call transfers into the
# existing voice-agent line (``/ws``) so the rebooking happens in the same
# call, in the caller's language, instead of promising a callback. These
# parameters travel on the Twilio ``<Stream>`` start message and land on
# ``CallSession.handoff``.
HANDOFF_PARAM = "vortex_handoff"
HANDOFF_RESCHEDULE = "reschedule"

_HANDOFF_BRIDGE: dict[str, tuple[str, str]] = {
    "es": (
        "es-ES",
        "Perfecto. Le paso con mi compañero, que es quien le agenda las citas. Un momento.",
    ),
    "ca": (
        "es-ES",
        "Perfecte. Li passo amb el meu company, que és qui li agenda les cites. Un moment.",
    ),
    "gl": (
        "es-ES",
        "Perfecto. Pásolle co meu compañeiro, que é quen lle axenda as citas. Un momento.",
    ),
    "eu": (
        "es-ES",
        "Primerik. Nire kidearekin pasatzen zaitut, hura da hitzorduak kudeatzen dituena. "
        "Itxaron pixka bat.",
    ),
    "en": (
        "en-US",
        "Of course. Let me hand you over to my colleague, who takes care of your bookings. "
        "One moment.",
    ),
}


def handoff_bridge_text(language: str | None) -> str:
    """The "le paso con mi compañero" line in the call's language."""
    return _HANDOFF_BRIDGE.get(call_language(language), _HANDOFF_BRIDGE["en"])[1]


def twiml_handoff_to_agent(
    call: ConfirmationCall, ws_url: str, *, audio_url: str | None = None
) -> str:
    """TwiML that bridges into the voice-agent websocket carrying the handoff."""
    voice, text = _HANDOFF_BRIDGE.get(call.language, _HANDOFF_BRIDGE["en"])
    params = {
        HANDOFF_PARAM: HANDOFF_RESCHEDULE,
        "appointment_id": call.appointment_id,
        "patient_id": call.patient_id,
        "language": call.language,
    }
    rendered = "".join(
        f"<Parameter name={quoteattr(k)} value={quoteattr(v)}/>" for k, v in params.items()
    )
    inner = _speech(voice, text, audio_url) + (
        f"<Connect><Stream url={quoteattr(ws_url)}>{rendered}</Stream></Connect>"
    )
    return twiml_response(inner)


def handoff_ws_url(public_base_url: str) -> str:
    """The ``/ws`` voice-agent URL behind the public base, as a websocket URL."""
    base = public_base_url.rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://") :]
    return base + "/ws"


# --- the wall's own voice for the Twilio-only segments -----------------------
#: Synthesis runs off the event loop with this budget; on any failure the
#: TwiML keeps its <Say>, so a TTS outage never breaks a confirmation call.
AUDIO_BUDGET_SECS = 8.0
_AUDIO_NAME_RE = re.compile(r"[0-9a-f]{24}\.mp3")


def confirmation_audio_dir(settings: Settings) -> Path:
    """Where the pre-rendered MP3s Twilio fetches are cached.

    A local scratch directory, not a store: these are regenerable files a
    redeploy is free to lose. ``VORTEX_CONFIRMATION_AUDIO_DIR`` moves it onto
    a volume when a deploy wants the cache to survive.
    """
    override = os.environ.get("VORTEX_CONFIRMATION_AUDIO_DIR", "").strip()
    if override:
        return Path(override)
    return REPO_ROOT / "logs" / "confirmation_audio"


def confirmation_voice_name(cfg: voice_config.VoiceConfig, language: str | None) -> str:
    """The Chirp 3 HD persona the wall configured, in the call's locale."""
    base = f"{twilio_locale(language)}-Chirp3-HD-{voice_config.FEMALE_PERSONA}"
    return voice_config.apply_gender(base, cfg.voice)


def audio_filename(cfg: voice_config.VoiceConfig, language: str | None, text: str) -> str:
    """Deterministic cache key: same words, voice and rate reuse the same MP3."""
    key = f"{cfg.voice}|{cfg.speech_rate}|{call_language(language)}|{text}"
    return hashlib.sha256(key.encode()).hexdigest()[:24] + ".mp3"


def valid_audio_name(name: str) -> bool:
    return bool(_AUDIO_NAME_RE.fullmatch(name))


async def ensure_confirmation_audio(settings: Settings, text: str, language: str) -> str | None:
    """The cached MP3 filename for one spoken line, in the wall's own voice.

    None means "keep the <Say>": no TTS credentials, a synthesis error or a
    slow Google all land there, and the call still says its line.
    """
    cfg = voice_config.load(settings)
    name = audio_filename(cfg, language, text)
    directory = confirmation_audio_dir(settings)
    if (directory / name).is_file():
        return name
    try:
        audio = await asyncio.wait_for(
            asyncio.to_thread(
                voice_config.synthesize,
                settings,
                cfg,
                text,
                language_code=twilio_locale(language),
                voice_name=confirmation_voice_name(cfg, language),
            ),
            timeout=AUDIO_BUDGET_SECS,
        )
    except Exception as exc:  # noqa: BLE001 - the <Say> fallback owns failures
        log.warning("confirmation audio unavailable, keeping <Say>: %s", exc)
        return None
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / f".{name}.tmp"
    tmp.write_bytes(audio)
    tmp.rename(directory / name)
    return name


def _speech(locale: str, text: str, audio_url: str | None) -> str:
    """A <Play> of the synthesised line when we have it, else a <Say>."""
    if audio_url:
        return f"<Play>{escape(audio_url)}</Play>"
    return f'<Say language="{locale}">{escape(text)}</Say>'


def handoff_from_parameters(params: dict[str, str]) -> dict[str, str] | None:
    """The reschedule handoff carried on a ``<Stream>`` start message, if any."""
    if params.get(HANDOFF_PARAM) != HANDOFF_RESCHEDULE:
        return None
    return {
        "kind": HANDOFF_RESCHEDULE,
        "appointment_id": str(params.get("appointment_id") or ""),
        "patient_id": str(params.get("patient_id") or ""),
        "language": str(params.get("language") or ""),
    }


def twiml_response(inner: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{inner}</Response>'


def ask_speech(call: ConfirmationCall, *, reprompt: bool = False) -> str:
    """The words the question (or its reprompt) speaks."""
    if reprompt:
        return ack_text("unknown", call.language)
    return ask_text(
        language=call.language,
        when=call.appointment_dt,
        provider_name=call.provider_name,
        location_name=call.location_name,
        motivo=call.motivo,
    )


def twiml_ask(
    call: ConfirmationCall,
    base_url: str,
    *,
    attempt: int = 1,
    reprompt: bool = False,
    audio_url: str | None = None,
) -> str:
    """The question Twilio plays. On silence the flow redirects to /noresult so
    an answered-but-quiet call is recorded instead of hanging as ``calling``."""
    base = base_url.rstrip("/")
    locale = twilio_locale(call.language)
    say = ask_speech(call, reprompt=reprompt)
    result_url = f"{base}/confirmation/result?cid={call.confirmation_id}&attempt={attempt}"
    gather = _gather(result_url, locale, say, audio_url=audio_url)
    noresult = f"{base}/confirmation/noresult?cid={call.confirmation_id}"
    return twiml_response(gather + f'<Redirect method="POST">{escape(noresult)}</Redirect>')


def twiml_say(text: str, language: str, *, audio_url: str | None = None) -> str:
    locale = twilio_locale(language)
    return twiml_response(_speech(locale, text, audio_url))


class CallJob(Protocol):
    """One kind of scheduled outbound call.

    The system owns the queue, the worker and the webhooks; a job owns only
    what makes it itself: when it fires, what it says, and how to read the
    answer.
    """

    job_id: str

    def call_at(self, *, when: datetime, lead: timedelta) -> datetime:
        """When the call should fire for an appointment starting at ``when``."""
        ...

    def ask_twiml(
        self,
        call: ConfirmationCall,
        base_url: str,
        *,
        attempt: int,
        reprompt: bool,
        audio_url: str | None = None,
    ) -> str: ...

    def ask_words(self, call: ConfirmationCall, *, reprompt: bool) -> str:
        """The words behind ``ask_twiml``'s ``<Gather>`` (or its reprompt) —
        what ``server.py`` synthesises/caches as ``audio_url`` before
        building the TwiML. Kept separate from ``ask_twiml`` because the
        audio has to exist *before* the TwiML that plays it, but must say
        exactly what that TwiML's own ``<Gather>`` asks."""
        ...

    def classify(self, transcript: str, language: str) -> CallOutcome: ...

    def ack(self, outcome: CallOutcome, language: str) -> str: ...

    def final_unclear(self, language: str) -> str: ...

    def no_speech(self, language: str) -> str: ...


CALL_JOBS: dict[str, CallJob] = {}


def register_job(job: CallJob) -> CallJob:
    """Add a job to the system. Dialing, webhooks and the store come with it."""
    CALL_JOBS[job.job_id] = job
    return job


def job_for(job_id: str) -> CallJob:
    try:
        return CALL_JOBS[job_id]
    except KeyError:
        raise KeyError(f"unknown scheduled-call job: {job_id!r}") from None


class AppointmentConfirmationJob:
    """Day-before "¿va a venir?" call. The system's first job."""

    job_id = "appointment_confirmation"

    def call_at(self, *, when: datetime, lead: timedelta) -> datetime:
        return when - lead

    def ask_twiml(
        self,
        call: ConfirmationCall,
        base_url: str,
        *,
        attempt: int,
        reprompt: bool,
        audio_url: str | None = None,
    ) -> str:
        return twiml_ask(call, base_url, attempt=attempt, reprompt=reprompt, audio_url=audio_url)

    def ask_words(self, call: ConfirmationCall, *, reprompt: bool) -> str:
        return ask_speech(call, reprompt=reprompt)

    def classify(self, transcript: str, language: str) -> CallOutcome:
        return classify_reply(transcript, language)

    def ack(self, outcome: CallOutcome, language: str) -> str:
        return ack_text(outcome, language)

    def final_unclear(self, language: str) -> str:
        return final_unclear_text(language)

    def no_speech(self, language: str) -> str:
        return no_speech_text(language)


register_job(AppointmentConfirmationJob())


# --- Cancellation rebooking: "your appointment was cancelled, want another
# date?" ----------------------------------------------------------------
#
# The job every cancellation (phone or wall) queues, immediately
# (motivo="call_now" — see queue_cancellation_rebooking_call). A genuinely
# different question from the day-before job ("was cancelled" vs. "will you
# come tomorrow"), so KNOWN_MOTIVOS' own rule applies: this is a new job,
# not a new entry in _MOTIVO_OPENING/_ASK.

_CANCEL_REBOOK_ASK: dict[str, str] = {
    "es": (
        "Hola, le llamamos de {clinic}. Su cita del {stamp}{with_whom} ha sido cancelada. "
        "¿Quiere que le busquemos otra fecha ahora mismo? Diga sí para buscar hueco, "
        "o no si no le interesa por ahora."
    ),
    "ca": (
        "Hola, li truquem de {clinic}. La seva cita del {stamp}{with_whom} ha estat cancel·lada. "
        "Vol que li busquem una altra data ara mateix? Digui sí per buscar hora, "
        "o no si ara no li interessa."
    ),
    "gl": (
        "Ola, chamámoslle de {clinic}. A súa cita do {stamp}{with_whom} foi cancelada. "
        "Quere que lle busquemos outra data agora mesmo? Diga si para buscar oco, "
        "ou non se agora non lle interesa."
    ),
    "eu": (
        "Kaixo, {clinic} koak gara. {stamp}{with_whom} zenuen hitzordua bertan behera geratu da. "
        "Beste data bat bilatzea nahi al duzu orain bertan? Esan bai bilatzeko, "
        "edo ez orain interesatzen ez bazaizu."
    ),
    "en": (
        "Hello, this is {clinic}. Your appointment on {stamp}{with_whom} has been cancelled. "
        "Would you like us to look for another date right now? Say yes to find a new slot, "
        "or no if you'd rather not right now."
    ),
}

_CANCEL_REBOOK_ACK: dict[str, dict[CallOutcome, str]] = {
    "es": {
        "reschedule_requested": (
            "Perfecto, en un momento le proponemos una nueva fecha. Gracias, adiós."
        ),
        "not_coming": (
            "De acuerdo, queda anotado. Puede llamarnos cuando quiera para buscar otra fecha. "
            "Gracias, adiós."
        ),
        "unknown": (
            "Perdone, no le he entendido. ¿Quiere que le busquemos otra fecha? Diga sí o no."
        ),
    },
    "ca": {
        "reschedule_requested": "Perfecte, en un moment li proposem una nova data. Gràcies, adéu.",
        "not_coming": (
            "D'acord, queda anotat. Truqui'ns quan vulgui per buscar una altra data. Gràcies, adéu."
        ),
        "unknown": "Perdoni, no l'he entès. Vol que li busquem una altra data? Digui sí o no.",
    },
    "gl": {
        "reschedule_requested": (
            "Perfecto, nun momento propoñémoslle unha nova data. Grazas, adeus."
        ),
        "not_coming": (
            "De acordo, queda anotado. Pode chamarnos cando queira para buscar outra data. "
            "Grazas, adeus."
        ),
        "unknown": "Perdone, non o entendín. Quere que lle busquemos outra data? Diga si ou non.",
    },
    "eu": {
        "reschedule_requested": (
            "Primeran, berehala beste data bat proposatuko dizugu. Eskerrik asko, agur."
        ),
        "not_coming": (
            "Ondo, ohartarazita geratu da. Nahi duzunean deitu diezagukezu beste data bat "
            "bilatzeko. Eskerrik asko, agur."
        ),
        "unknown": "Barkatu, ez zaitut ulertu. Beste data bat bilatzea nahi duzu? Esan bai edo ez.",
    },
    "en": {
        "reschedule_requested": (
            "Perfect, we'll propose a new date in just a moment. Thank you, goodbye."
        ),
        "not_coming": (
            "Understood, that's noted. You can call us anytime to look for another date. "
            "Thank you, goodbye."
        ),
        "unknown": (
            "Sorry, I didn't catch that. Would you like us to look for another date? Say yes or no."
        ),
    },
}


def cancellation_rebooking_ask_text(
    *,
    language: str,
    when: datetime,
    provider_name: str = "",
    location_name: str = "",
    clinic_name: str = CLINIC_NAME,
) -> str:
    lang = call_language(language)
    return _CANCEL_REBOOK_ASK[lang].format(
        clinic=clinic_name,
        with_whom=_with_whom_clause(lang, provider_name, location_name),
        stamp=_stamp_for(lang, when),
    )


def cancellation_rebooking_ack_text(outcome: CallOutcome, language: str) -> str:
    by_outcome = _CANCEL_REBOOK_ACK[call_language(language)]
    return by_outcome.get(outcome, by_outcome["unknown"])


def cancellation_rebooking_ask_speech(call: ConfirmationCall, *, reprompt: bool = False) -> str:
    if reprompt:
        return cancellation_rebooking_ack_text("unknown", call.language)
    return cancellation_rebooking_ask_text(
        language=call.language,
        when=call.appointment_dt,
        provider_name=call.provider_name,
        location_name=call.location_name,
    )


def classify_cancellation_reply(transcript: str, language: str | None = None) -> CallOutcome:
    """Keyword classification for the cancellation-rebooking call. There is
    no "will you come" question here — any "yes" (or an explicit reschedule
    word) means the patient wants another date, so both fold onto
    ``reschedule_requested``, the same outcome the day-before job's own
    in-call handoff already keys on (see server.py's ``/confirmation/result``).
    A plain "no" means they don't want one right now."""
    folded = _fold(transcript)
    if not folded.strip():
        return "unknown"
    lang = call_language(language)
    if _matches(folded, _RESCHEDULE[lang]) or _matches(folded, _YES[lang]):
        return "reschedule_requested"
    if _matches(folded, _NO[lang]):
        return "not_coming"
    return "unknown"


class CancellationRebookingJob:
    """ "Your appointment was cancelled, want another date?" — see the
    module-level comment above for why this is its own job rather than a
    new ``motivo`` on ``AppointmentConfirmationJob``."""

    job_id = CANCELLATION_REBOOKING_JOB

    def call_at(self, *, when: datetime, lead: timedelta) -> datetime:
        # Never actually used: every row this job places carries
        # motivo="call_now", which bypasses this schedule entirely (see
        # build_confirmation_call). Kept only for Protocol conformance.
        return when - lead

    def ask_twiml(
        self,
        call: ConfirmationCall,
        base_url: str,
        *,
        attempt: int,
        reprompt: bool,
        audio_url: str | None = None,
    ) -> str:
        base = base_url.rstrip("/")
        locale = twilio_locale(call.language)
        say = cancellation_rebooking_ask_speech(call, reprompt=reprompt)
        result_url = f"{base}/confirmation/result?cid={call.confirmation_id}&attempt={attempt}"
        gather = _gather(result_url, locale, say, audio_url=audio_url)
        noresult = f"{base}/confirmation/noresult?cid={call.confirmation_id}"
        return twiml_response(gather + f'<Redirect method="POST">{escape(noresult)}</Redirect>')

    def ask_words(self, call: ConfirmationCall, *, reprompt: bool) -> str:
        return cancellation_rebooking_ask_speech(call, reprompt=reprompt)

    def classify(self, transcript: str, language: str) -> CallOutcome:
        return classify_cancellation_reply(transcript, language)

    def ack(self, outcome: CallOutcome, language: str) -> str:
        return cancellation_rebooking_ack_text(outcome, language)

    def final_unclear(self, language: str) -> str:
        return final_unclear_text(language)

    def no_speech(self, language: str) -> str:
        return no_speech_text(language)


register_job(CancellationRebookingJob())


@dataclass
class ConfirmationCall:
    confirmation_id: str
    to: str
    appointment_at: str  # ISO-8601 with offset
    call_at: str  # ISO-8601 with offset
    language: str = DEFAULT_CALL_LANGUAGE
    provider_name: str = ""
    location_name: str = ""
    patient_id: str = ""
    provider_id: str = ""
    location_id: str = ""
    appointment_id: str = ""
    job: str = "appointment_confirmation"
    #: Why this call is happening — see ``KNOWN_MOTIVOS``. Every row queued
    #: from an accepted ``BookAction`` keeps the default, ``"confirmacion"``.
    motivo: str = DEFAULT_MOTIVO
    status: ConfirmationStatus = "pending"
    detail: str = ""
    twilio_call_sid: str = ""
    transcript: str = ""
    attempts: int = 0

    @property
    def appointment_dt(self) -> datetime:
        return datetime.fromisoformat(self.appointment_at)

    @property
    def call_dt(self) -> datetime:
        return datetime.fromisoformat(self.call_at)


def default_calls_path(settings: Settings) -> Path:
    """The outbound-call queue file. Local scratch, overridden by
    ``VORTEX_CONFIRMATION_CALLS_PATH``; the durable copy of every queued call
    is the ``calls`` row ``_persist_call_now_row`` writes."""
    return REPO_ROOT / "logs" / "confirmation_calls.json"


#: One store per resolved path, so the asyncio.Lock is shared by the webhooks,
#: the worker and the booking session alike. Without this each built its own
#: instance and a concurrent read-modify-write lost rows (double-dialling).
_STORES: dict[Path, ConfirmationStore] = {}


def confirmation_store_from_settings(settings: Settings) -> ConfirmationStore:
    path = (
        Path(settings.confirmation_calls_path)
        if settings.confirmation_calls_path
        else default_calls_path(settings)
    )
    store = _STORES.get(path)
    if store is None:
        store = ConfirmationStore(path)
        _STORES[path] = store
    return store


class ConfirmationStore:
    """Tiny JSON list of confirmation calls. One process, one lock.

    Same shape as ``sms_reminders.ReminderStore``: a restart loses nothing and
    the demo can point at the file directly.
    """

    def __init__(self, path: Path):
        self.path = path
        self._lock = asyncio.Lock()

    def _read(self) -> list[ConfirmationCall]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.exception("confirmation call store unreadable: %s", self.path)
            return []
        if not isinstance(raw, list):
            return []
        out: list[ConfirmationCall] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            try:
                known = {
                    key: value
                    for key, value in row.items()
                    if key in ConfirmationCall.__dataclass_fields__
                }
                out.append(ConfirmationCall(**known))
            except TypeError:
                continue
        return out

    def _write(self, rows: list[ConfirmationCall]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    async def add(self, call: ConfirmationCall) -> ConfirmationCall:
        async with self._lock:
            rows = self._read()
            # Dedup keys on motivo too: a pending "confirmacion" and a
            # pending "recordatorio" for the same phone+slot are two
            # different calls the patient should get, neither replaces the
            # other. Two calls of the *same* motivo for the same phone+slot
            # are the same call queued twice — the newer one wins.
            rows = [
                row
                for row in rows
                if not (
                    row.status == "pending"
                    and row.to == call.to
                    and row.appointment_at == call.appointment_at
                    and row.motivo == call.motivo
                )
            ]
            rows.append(call)
            self._write(rows)
            return call

    async def get(self, confirmation_id: str) -> ConfirmationCall | None:
        async with self._lock:
            for row in self._read():
                if row.confirmation_id == confirmation_id:
                    return row
            return None

    async def cancel_matching(
        self,
        *,
        to: str = "",
        appointment_at: str = "",
        appointment_id: str = "",
    ) -> int:
        async with self._lock:
            rows = self._read()
            cancelled = 0
            for row in rows:
                if row.status != "pending":
                    continue
                if appointment_id and row.appointment_id == appointment_id:
                    row.status = "cancelled"
                    row.detail = "cancelled_by_appointment_id"
                    cancelled += 1
                    continue
                if appointment_at and row.appointment_at == appointment_at:
                    if to and row.to != to:
                        continue
                    row.status = "cancelled"
                    row.detail = "cancelled_by_slot"
                    cancelled += 1
            if cancelled:
                self._write(rows)
            return cancelled

    async def claim_due(self, now: datetime) -> list[ConfirmationCall]:
        """Flip due pending rows to ``calling`` so two polls cannot double-dial."""
        async with self._lock:
            rows = self._read()
            due: list[ConfirmationCall] = []
            changed = False
            now_aware = now if now.tzinfo is not None else now.replace(tzinfo=MADRID)
            for row in rows:
                if row.status != "pending":
                    continue
                try:
                    call_at = row.call_dt
                except ValueError:
                    row.status = "skipped"
                    row.detail = "bad_call_at"
                    changed = True
                    continue
                if call_at.tzinfo is None:
                    call_at = call_at.replace(tzinfo=MADRID)
                if call_at <= now_aware:
                    row.status = "calling"
                    row.detail = "claimed"
                    due.append(ConfirmationCall(**asdict(row)))
            if due or changed:
                self._write(rows)
            return due

    async def update(self, confirmation_id: str, **changes: Any) -> ConfirmationCall | None:
        async with self._lock:
            rows = self._read()
            updated: ConfirmationCall | None = None
            for row in rows:
                if row.confirmation_id == confirmation_id:
                    for key, value in changes.items():
                        if hasattr(row, key):
                            setattr(row, key, value)
                    updated = ConfirmationCall(**asdict(row))
                    break
            if updated is not None:
                self._write(rows)
            return updated


@dataclass(frozen=True)
class CallResult:
    status: Literal["queued", "dry_run", "failed"]
    detail: str = ""
    sid: str = ""


class CallsClient(Protocol):
    async def place(self, *, to: str, twiml_url: str, status_callback_url: str) -> CallResult: ...

    async def aclose(self) -> None: ...


class DryRunCallsClient:
    """No Twilio keys or no public URL. Records what would have been dialled."""

    def __init__(self, reason: str = "") -> None:
        self.placed: list[dict[str, str]] = []
        self.reason = reason or "no Twilio credentials or no public base URL: not dialled"

    async def place(self, *, to: str, twiml_url: str, status_callback_url: str) -> CallResult:
        self.placed.append({"to": to, "twiml_url": twiml_url})
        return CallResult(status="dry_run", detail=self.reason)

    async def aclose(self) -> None:
        return None


class TwilioCallsClient:
    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        *,
        from_number: str,
        timeout: float = CALL_BUDGET_SECS,
    ):
        if not from_number:
            raise ValueError("Twilio calls need TWILIO_FROM_NUMBER")
        self._from_number = from_number
        self._http = httpx.AsyncClient(auth=(account_sid, auth_token), timeout=timeout)
        self._url = TWILIO_CALLS_URL.format(account_sid=account_sid)

    async def place(self, *, to: str, twiml_url: str, status_callback_url: str) -> CallResult:
        # No Method/StatusCallbackMethod: Twilio defaults both to POST, and a
        # trial account rejects the explicit parameter outright.
        data = {
            "To": to,
            "From": self._from_number,
            "Url": twiml_url,
            "StatusCallback": status_callback_url,
            "StatusCallbackEvent": "completed no-answer busy failed canceled",
        }
        try:
            response = await self._http.post(self._url, data=data)
        except httpx.HTTPError as exc:
            return CallResult(status="failed", detail=f"{type(exc).__name__}: {exc}")
        if response.status_code in (200, 201):
            sid = ""
            try:
                sid = str(response.json().get("sid") or "")
            except ValueError:
                sid = ""
            return CallResult(status="queued", detail="accepted by Twilio", sid=sid)
        return CallResult(
            status="failed", detail=f"HTTP {response.status_code}: {response.text[:300]}"
        )

    async def aclose(self) -> None:
        await self._http.aclose()


def twilio_calls_configured(settings: Settings) -> bool:
    """True when a real call can be attempted: keys, a From number and the
    public URL Twilio fetches the TwiML from."""
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        return False
    if not settings.twilio_from_number:
        return False
    return bool(settings.public_base_url)


def make_calls_client(settings: Settings) -> DryRunCallsClient | TwilioCallsClient:
    if twilio_calls_configured(settings):
        return TwilioCallsClient(
            settings.twilio_account_sid,
            settings.twilio_auth_token,
            from_number=settings.twilio_from_number,
        )
    return DryRunCallsClient()


def build_confirmation_call(
    *,
    to: str,
    when: datetime,
    job: str = "appointment_confirmation",
    language: str = "",
    provider_name: str = "",
    location_name: str = "",
    provider_id: str = "",
    location_id: str = "",
    patient_id: str = "",
    appointment_id: str = "",
    now: datetime,
    lead: timedelta | None = None,
    motivo: str = DEFAULT_MOTIVO,
) -> ConfirmationCall | None:
    """Return a pending call for ``when - lead``, or ``None`` when that is past.

    ``motivo="call_now"`` is the one exception to both guards below: it skips
    the 24h booking-gap rule and the lead-based schedule entirely and sets
    ``call_at`` to ``now``, so ``ConfirmationWorker.tick`` claims and dials it
    on its very next poll — see ``KNOWN_MOTIVOS`` and the module README for
    how to enqueue one by hand.
    """
    if when.tzinfo is None:
        raise ValueError(f"appointment datetime must carry an offset: {when.isoformat()}")
    clock = now if now.tzinfo is not None else now.replace(tzinfo=MADRID)
    if motivo == "call_now":
        call_at = clock
    else:
        if when - clock < MIN_BOOKING_GAP:
            return None
        gap = lead if lead is not None else timedelta(days=1)
        call_at = job_for(job).call_at(when=when, lead=gap)
        if call_at <= clock:
            return None
    return ConfirmationCall(
        confirmation_id=uuid.uuid4().hex,
        job=job,
        motivo=motivo,
        to=to,
        appointment_at=when.isoformat(),
        call_at=call_at.isoformat(),
        language=call_language(language),
        provider_name=provider_name,
        location_name=location_name,
        patient_id=patient_id,
        provider_id=provider_id,
        location_id=location_id,
        appointment_id=appointment_id,
        status="pending",
    )


async def schedule_confirmation_call(
    store: ConfirmationStore,
    *,
    to: str,
    when: datetime,
    job: str = "appointment_confirmation",
    language: str = "",
    provider_name: str = "",
    location_name: str = "",
    provider_id: str = "",
    location_id: str = "",
    patient_id: str = "",
    appointment_id: str = "",
    now: datetime,
    lead: timedelta | None = None,
    motivo: str = DEFAULT_MOTIVO,
) -> ConfirmationCall | None:
    call = build_confirmation_call(
        to=to,
        when=when,
        job=job,
        language=language,
        provider_name=provider_name,
        location_name=location_name,
        provider_id=provider_id,
        location_id=location_id,
        patient_id=patient_id,
        appointment_id=appointment_id,
        now=now,
        lead=lead,
        motivo=motivo,
    )
    if call is None:
        return None
    return await store.add(call)


async def cancel_confirmation_calls(
    store: ConfirmationStore,
    *,
    to: str = "",
    appointment_at: datetime | None = None,
    appointment_id: str = "",
) -> int:
    return await store.cancel_matching(
        to=to,
        appointment_at=appointment_at.isoformat() if appointment_at is not None else "",
        appointment_id=appointment_id,
    )


#: DB-safe ``calls.outcome`` for each terminal status the cancellation
#: rebooking call can resolve to. ``database/schema.py``'s CHECK on
#: ``calls.outcome`` is the submit contract's own closed vocabulary plus
#: confirmed/no_answer — a ``ConfirmationStatus`` with no honest match
#: (unclear/failed/skipped/cancelled/pending/calling) leaves ``outcome``
#: alone instead of lying; ``detail`` still records it (see
#: ``sync_call_now_outcome_to_db``).
_CALL_NOW_DB_OUTCOME: dict[str, str] = {
    "confirmed": "confirmed",
    "reschedule_requested": "reschedule",
    "not_coming": "no_action",
    "no_answer": "no_answer",
}


async def queue_cancellation_rebooking_call(
    settings: Settings,
    *,
    to: str,
    appointment_at: datetime,
    language: str = "",
    provider_name: str = "",
    location_name: str = "",
    provider_id: str = "",
    location_id: str = "",
    patient_id: str = "",
    appointment_id: str = "",
    now: datetime,
    already_offered_reschedule: bool = False,
) -> ConfirmationCall | None:
    """Queue the "your appointment was cancelled, want another date?" call —
    the one every cancellation (phone or wall) fires, immediately
    (``motivo="call_now"``, see ``build_confirmation_call``). Mirrors the
    queued row into the product database too (``_persist_call_now_row``),
    not just ``logs/confirmation_calls.json``.

    ``already_offered_reschedule`` is the loop guard: a cancellation reached
    *through* this very job's own in-call handoff (``CallSession.handoff``)
    already asked "¿otra fecha?" live, on that call, so queuing a fresh
    call_now on top would re-dial someone who is (or just was) on the phone
    with us. ``to`` empty or the subsystem disabled
    (``VORTEX_CONFIRMATION_CALLS``) also return ``None`` without raising.
    The store's own dedup (same phone + same slot + motivo="call_now")
    covers the rest — cancelling the same visit twice must not queue two
    calls.
    """
    if already_offered_reschedule or not to.strip() or not settings.confirmation_calls:
        return None
    store = confirmation_store_from_settings(settings)
    call = await schedule_confirmation_call(
        store,
        to=to,
        when=appointment_at,
        job=CANCELLATION_REBOOKING_JOB,
        language=language,
        provider_name=provider_name,
        location_name=location_name,
        provider_id=provider_id,
        location_id=location_id,
        patient_id=patient_id,
        appointment_id=appointment_id,
        now=now,
        motivo="call_now",
    )
    if call is not None:
        _persist_call_now_row(call)
    return call


def _persist_call_now_row(call: ConfirmationCall) -> None:
    """Mirror the queued call_now row into ``public.calls`` — not just
    ``logs/confirmation_calls.json`` — so the wall and the board see it.
    ``call.confirmation_id`` is written as the row's own ``call_id``, so
    ``sync_call_now_outcome_to_db`` can find it again once the call resolves.

    The appointment link is skipped, not faked, when the cancelled
    appointment has no row here yet — most wall-cancelled visits are the
    read-only clinic's own seed data; the outbound call itself is still
    recorded. Never raises: a store hiccup must not stop the call from being
    queued.
    """
    try:
        from database import db

        appointment_id = call.appointment_id or None
        if appointment_id and db.get_appointment(appointment_id) is None:
            appointment_id = None
        db.insert_call(
            call_id=call.confirmation_id,
            direction="outbound",
            purpose="reschedule",
            language=call.language,
            from_number=call.to,
            started_at=db.now_iso(),
            appointment_id=appointment_id,
            motivo=call.motivo,
        )
    except Exception:
        log.exception("could not persist call_now row for confirmation %s", call.confirmation_id)


def sync_call_now_outcome_to_db(
    *,
    confirmation_id: str,
    motivo: str,
    settings: Settings,
    status: str = "",
    transcript: str = "",
    detail: str = "",
) -> None:
    """Mirror a call_now confirmation call's answer back into the same
    ``calls`` row ``_persist_call_now_row`` wrote when it was queued — the
    wall (and anything else reading the store instead of
    ``logs/confirmation_calls.json``) needs the outcome, not just the queue
    entry.

    Scoped to ``motivo == "call_now"``: the day-before confirmation job has
    its own, separate database story (``database/confirmations.py``) this
    does not touch. A no-op when neither an outcome, a transcript nor a
    detail changed. Never raises.
    """
    if motivo != "call_now":
        return
    outcome = _CALL_NOW_DB_OUTCOME.get(status)
    if outcome is None and not transcript and not detail:
        return
    try:
        from database import db

        db.update_call_outcome(
            confirmation_id,
            outcome=outcome,
            transcript=transcript or None,
            detail=detail or None,
        )
    except Exception:
        log.exception("could not sync call_now outcome for confirmation %s", confirmation_id)


class ConfirmationWorker:
    """Polls the store and dials what is due. Mirrors ``ReminderWorker``."""

    def __init__(
        self,
        settings: Settings,
        *,
        store: ConfirmationStore | None = None,
        calls: DryRunCallsClient | TwilioCallsClient | None = None,
        poll_secs: float | None = None,
    ):
        self.settings = settings
        self.store = store or confirmation_store_from_settings(settings)
        self.calls = calls or make_calls_client(settings)
        self.poll_secs = (
            poll_secs if poll_secs is not None else float(settings.confirmation_poll_secs or 30.0)
        )
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="confirmation-call-worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self.calls.aclose()

    async def _run(self) -> None:
        log.info(
            "confirmation call worker on (%s), poll=%.1fs",
            self.store.path,
            self.poll_secs,
        )
        while not self._stop.is_set():
            try:
                await self.tick(datetime.now(tz=MADRID))
            except Exception:  # noqa: BLE001 - worker must keep looping
                log.exception("confirmation call tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_secs)
            except TimeoutError:
                continue

    def _urls(self, call: ConfirmationCall) -> tuple[str, str]:
        base = self.settings.public_base_url.rstrip("/")
        return (
            f"{base}/confirmation/twiml?cid={call.confirmation_id}",
            f"{base}/confirmation/status?cid={call.confirmation_id}",
        )

    async def tick(self, now: datetime) -> int:
        due = await self.store.claim_due(now)
        for row in due:
            twiml_url, status_url = self._urls(row)
            try:
                result = await self.calls.place(
                    to=row.to, twiml_url=twiml_url, status_callback_url=status_url
                )
                if result.status == "queued":
                    await self.store.update(
                        row.confirmation_id,
                        status="calling",
                        detail=result.detail,
                        twilio_call_sid=result.sid,
                    )
                elif result.status == "dry_run":
                    await self.store.update(
                        row.confirmation_id, status="skipped", detail=result.detail
                    )
                else:
                    await self.store.update(
                        row.confirmation_id, status="failed", detail=result.detail
                    )
                log.info(
                    "confirmation call %s -> %s (%s)",
                    row.confirmation_id,
                    result.status,
                    result.detail,
                )
            except Exception as exc:  # noqa: BLE001
                await self.store.update(row.confirmation_id, status="failed", detail=repr(exc))
                log.exception("confirmation call %s failed", row.confirmation_id)
        return len(due)


def confirmation_worker_status(worker: ConfirmationWorker | None) -> dict[str, Any]:
    if worker is None:
        return {"confirmation_calls_worker": False}
    return {
        "confirmation_calls_worker": True,
        "confirmation_calls_path": str(worker.store.path),
        "confirmation_poll_secs": worker.poll_secs,
    }
