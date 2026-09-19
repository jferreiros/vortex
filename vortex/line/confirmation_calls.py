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
per appointment.

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
import json
import logging
import re
import unicodedata
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol
from xml.sax.saxutils import escape

import httpx

from vortex.contract import MADRID
from vortex.conversation.prompt import CLINIC_NAME
from vortex.line.sms import format_slot_es
from vortex.settings import Settings

log = logging.getLogger("vortex.line.confirmation_calls")

TWILIO_CALLS_URL = "https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls.json"

CALL_BUDGET_SECS = 8.0

#: Product rule (Cristina, 2026-09-19): an appointment booked less than 24 h
#: before its slot gets no confirmation call at all - the patient just booked
#: it, there is nothing to remind. Hard-coded, not the lead: the lead is a demo
#: knob, this rule is not.
MIN_BOOKING_GAP = timedelta(hours=24)

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


_ASK = {
    "es": (
        "Hola, le llamamos de {clinic} para confirmar su cita. "
        "Mañana tiene cita{with_whom}: {stamp}. "
        "¿Va a venir? Diga sí para confirmar. Si prefiere cambiarla, dígamelo y la movemos "
        "ahora mismo. Si no puede venir, diga no."
    ),
    "ca": (
        "Hola, li truquem de {clinic} per confirmar la seva cita de demà{with_whom}: {stamp}. "
        "Hi vindrà? Digui sí per confirmar. Si prefereix canviar-la, m'ho diu i la movem ara "
        "mateix. Si no hi pot venir, digui no."
    ),
    "gl": (
        "Hola, chamámoslle de {clinic} para confirmar a súa cita de mañá{with_whom}: {stamp}. "
        "Vai vir? Diga si para confirmar. Se prefire cambiala, dígamo e movémola agora mesmo. "
        "Se non pode vir, diga non."
    ),
    "eu": (
        "Kaixo, {clinic} koak gara, biharko hitzordua{with_whom} "
        "berresteko deitzen dizugu: {stamp}. "
        "Etorriko al zara? Esan bai berresteko. Aldatzea nahiago baduzu, esadazu eta oraintxe "
        "bertan mugituko dugu. Ezin bazara etorri, esan ez."
    ),
    "en": (
        "Hello, this is {clinic} calling to confirm your appointment tomorrow{with_whom}: {stamp}. "
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


def ask_text(
    *,
    language: str,
    when: datetime,
    provider_name: str = "",
    location_name: str = "",
    clinic_name: str = CLINIC_NAME,
) -> str:
    lang = call_language(language)
    provider, location = _named(provider_name, location_name)
    with_whom = ""
    if provider and location:
        with_whom = _WITH_WHOM[lang].format(provider=provider, location=location)
    elif provider and lang in ("es", "gl", "en"):
        with_whom = {"es": " con {p}", "gl": " con {p}", "en": " with {p}"}[lang].format(p=provider)
    return _ASK[lang].format(clinic=clinic_name, with_whom=with_whom, stamp=_stamp_for(lang, when))


def ack_text(outcome: CallOutcome, language: str) -> str:
    return _ACK[call_language(language)][outcome]


def no_speech_text(language: str) -> str:
    return _NO_SPEECH[call_language(language)]


def _gather(action_url: str, locale: str, say: str, *, timeout: int = 10) -> str:
    return (
        f'<Gather input="speech" language="{locale}" action="{escape(action_url)}" '
        f'method="POST" speechTimeout="auto" timeout="{timeout}">'
        f'<Say language="{locale}">{escape(say)}</Say>'
        f"</Gather>"
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
    "es": ("es-ES", "Perfecto, le paso con nuestro agente para mover la cita. Un momento."),
    "ca": ("es-ES", "Perfecte, li passo amb el nostre agent per moure la cita. Un moment."),
    "gl": ("es-ES", "Perfecto, pásolle co noso axente para mover a cita. Un momento."),
    "eu": (
        "es-ES",
        "Primerik, gure agentearekin pasatzen zaitut hitzordua mugitzeko. Itxaron pixka bat.",
    ),
    "en": (
        "en-US",
        "Of course, I'll connect you with our agent to move the appointment. One moment.",
    ),
}


def twiml_handoff_to_agent(call: ConfirmationCall, ws_url: str) -> str:
    """TwiML that bridges into the voice-agent websocket carrying the handoff."""
    voice, text = _HANDOFF_BRIDGE.get(call.language, _HANDOFF_BRIDGE["en"])
    params = {
        HANDOFF_PARAM: HANDOFF_RESCHEDULE,
        "appointment_id": call.appointment_id,
        "patient_id": call.patient_id,
        "language": call.language,
    }
    rendered = "".join(
        f'<Parameter name="{escape(k)}" value="{escape(v)}"/>' for k, v in params.items()
    )
    inner = (
        f'<Say language="{voice}">{escape(text)}</Say>'
        f'<Connect><Stream url="{escape(ws_url)}">{rendered}</Stream></Connect>'
    )
    return twiml_response(inner)


def handoff_ws_url(public_base_url: str) -> str:
    """The ``/ws`` voice-agent URL behind the public base, as a websocket URL."""
    base = public_base_url.rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://"):]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://"):]
    return base + "/ws"


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


# --- Twilio-only in-call rebooking -----------------------------------------
# When no live voice pipeline runs behind this server (stub/demo), a "change
# it" answer still moves the appointment inside the same call: the clinic's
# availability feeds a short offer-and-pick loop over Gather. The live-voice
# handoff above stays the full rebooking experience; this loop keeps the
# script's promise - "la movemos ahora mismo" - true on every setup.

_PICK_ORDINALS: dict[str, list[list[str]]] = {
    "es": [["uno", "primera", "el uno", "la primera"], ["dos", "segunda"], ["tres", "tercera"]],
    "ca": [["u", "primera"], ["dos", "segona"], ["tres", "tercera"]],
    "gl": [["un", "primeiro"], ["dous", "segundo"], ["tres", "terceiro"]],
    "eu": [["bat", "lehena"], ["bi", "bigarrena"], ["hiru", "hirugarrena"]],
    "en": [["one", "first"], ["two", "second"], ["three", "third"]],
}

_WEEKDAY_WORDS: dict[str, list[str]] = {
    "es": ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"],
    "en": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
}

_PICK_NONE = {
    "es": ["ninguna", "ninguno", "no me viene", "no me vale"],
    "ca": ["cap"],
    "gl": ["ningun", "ningunha"],
    "eu": ["bat ere ez"],
    "en": ["none", "neither", "no thanks"],
}

_RESCHEDULE_OFFER = {
    "es": (
        "De acuerdo, la movemos ahora mismo. Tengo estos huecos: {options}. "
        "Diga uno, dos o tres, o ninguna si ninguna le viene bien."
    ),
    "ca": (
        "D'acord, la movem ara mateix. Tinc aquests forats: {options}. "
        "Digui u, dos o tres, o cap si cap li va bé."
    ),
    "gl": (
        "De acordo, movémola agora mesmo. Teño estes ocos: {options}. "
        "Diga un, dous ou tres, ou ningún se ningún lle ven ben."
    ),
    "eu": (
        "Ondo, oraintxe mugituko dugu. Tarteko hauek ditut: {options}. "
        "Esan bat, bi edo hiru, edo bat ere ez ezean."
    ),
    "en": (
        "Of course, let's move it right now. I have these openings: {options}. "
        "Say one, two or three, or none if none of them works for you."
    ),
}

_PICK_UNKNOWN = {
    "es": "Perdone, no le he entendido. Diga uno, dos o tres.",
    "ca": "Perdó, no li he entès. Digui u, dos o tres.",
    "gl": "Perdón, non o entendín. Diga un, dous ou tres.",
    "eu": "Barkatu, ez zaitut ulertu. Esan bat, bi edo hiru.",
    "en": "Sorry, I didn't catch that. Say one, two or three.",
}

_RESCHEDULE_DONE = {
    "es": "Perfecto, su cita queda movida a {stamp}. Gracias, adiós.",
    "ca": "Perfecte, la seva cita queda moguda a {stamp}. Gràcies, adéu.",
    "gl": "Perfecto, a súa cita queda movida a {stamp}. Grazas, adeus.",
    "eu": "Primerik, zure hitzordua {stamp} datara mugitu da. Eskerrik asko, agur.",
    "en": "Perfect, your appointment is moved to {stamp}. Thank you, goodbye.",
}


async def pick_reschedule_slots(
    clinic: Any, call: ConfirmationCall, *, days: int = 7, limit: int = 3
) -> list[Any]:
    """The first bookable slots after the current appointment, same provider.

    The platform's availability endpoint needs a provider or a specialty; the
    confirmation row carries the provider id, so an appointment seeded without
    one simply cannot be moved this way and the caller gets the callback.
    """
    if not call.provider_id:
        return []
    start_day = call.appointment_dt.date() + timedelta(days=1)
    try:
        availability = await clinic.availability(
            date_from=start_day,
            date_to=start_day + timedelta(days=days),
            provider_id=call.provider_id,
        )
    except Exception:
        log.warning("confirmation %s: availability lookup failed", call.confirmation_id)
        return []
    # One opening per day: three slots on the same morning are one real option.
    spread: list[Any] = []
    seen_days: set[Any] = set()
    for slot in availability.slots:
        if slot.start.date() in seen_days:
            continue
        seen_days.add(slot.start.date())
        spread.append(slot)
        if len(spread) == limit:
            break
    return spread


def offered_slots_payload(slots: list[Any]) -> str:
    """The offered slots, persisted on the row so the pick webhook can score."""
    return json.dumps(
        [
            {
                "start": slot.start.isoformat(),
                "provider_id": slot.provider_id,
                "location_id": slot.location_id,
                "appointment_type_id": slot.appointment_type_id,
            }
            for slot in slots
        ]
    )


def parse_offered_slots(payload: str) -> list[datetime]:
    """What the call offered, as start datetimes in offer order."""
    try:
        rows = json.loads(payload) if payload else []
    except json.JSONDecodeError:
        return []
    starts = []
    for row in rows:
        try:
            starts.append(datetime.fromisoformat(row["start"]))
        except (KeyError, ValueError):
            return []
    return starts


def reschedule_offer_text(language: str, starts: list[datetime]) -> str:
    lang = call_language(language)
    options = "; ".join(
        f"{_PICK_ORDINALS[lang][i][0]}: {_stamp_for(lang, start)}"
        for i, start in enumerate(starts)
    )
    return _RESCHEDULE_OFFER[lang].format(options=options)


def twiml_reschedule_offer(
    call: ConfirmationCall, base_url: str, starts: list[datetime], *, attempt: int = 1,
    reprompt: bool = False,
) -> str:
    """The offer TwiML: the openings plus a speech-or-one-key Gather."""
    base = base_url.rstrip("/")
    lang = call_language(call.language)
    locale = twilio_locale(call.language)
    say = (
        _PICK_UNKNOWN[lang]
        if reprompt
        else reschedule_offer_text(call.language, starts)
    )
    action = f"{base}/confirmation/reschedule-pick?cid={call.confirmation_id}&attempt={attempt}"
    gather = (
        f'<Gather input="speech dtmf" numDigits="1" language="{locale}" '
        f'action="{escape(action)}" method="POST" speechTimeout="auto" timeout="10">'
        f'<Say language="{locale}">{escape(say)}</Say></Gather>'
    )
    noresult = (
        f"{base}/confirmation/reschedule-pick"
        f"?cid={call.confirmation_id}&attempt={attempt + 1}"
    )
    return twiml_response(gather + f'<Redirect method="POST">{escape(noresult)}</Redirect>')


def classify_slot_pick(
    transcript: str, digits: str, starts: list[datetime], language: str
) -> int | None | str:
    """Which offered slot the caller picked: an index, "none", or None (retry).

    Accepts the one-key DTMF answer, the ordinal in the call's language, and -
    in Spanish and English - the weekday the slot falls on ("martes").
    """
    lang = call_language(language)
    if digits.isdigit():
        index = int(digits) - 1
        if 0 <= index < len(starts):
            return index
    folded = _fold(transcript)
    if any(word in folded for word in _PICK_NONE[lang]):
        return "none"
    for index, words in enumerate(_PICK_ORDINALS[lang][: len(starts)]):
        if any(word in folded for word in words):
            return index
    time_match = re.search(r"(\d{1,2})[:.](\d{2})", folded)
    if time_match is None:
        time_match = re.search(r"las (\d{1,2}) y media", folded)
        if time_match is not None:
            matches = [
                i for i, start in enumerate(starts)
                if start.hour == int(time_match.group(1)) and start.minute == 30
            ]
            if len(matches) == 1:
                return matches[0]
    if time_match is not None and time_match.lastindex and time_match.lastindex >= 2:
        matches = [
            i
            for i, start in enumerate(starts)
            if start.hour == int(time_match.group(1)) and start.minute == int(time_match.group(2))
        ]
        if len(matches) == 1:
            return matches[0]
    for weekday_words in _WEEKDAY_WORDS.values():
        for weekday, word in enumerate(weekday_words):
            if word in folded:
                matches = [i for i, start in enumerate(starts) if start.weekday() == weekday]
                if len(matches) == 1:
                    return matches[0]
    return None


def reschedule_done_text(language: str, start: datetime) -> str:
    lang = call_language(language)
    return _RESCHEDULE_DONE[lang].format(stamp=_stamp_for(lang, start))


def twiml_response(inner: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{inner}</Response>'


def twiml_ask(
    call: ConfirmationCall, base_url: str, *, attempt: int = 1, reprompt: bool = False
) -> str:
    """The question Twilio plays. On silence the flow redirects to /noresult so
    an answered-but-quiet call is recorded instead of hanging as ``calling``."""
    base = base_url.rstrip("/")
    locale = twilio_locale(call.language)
    say = (
        ack_text("unknown", call.language)
        if reprompt
        else ask_text(
            language=call.language,
            when=call.appointment_dt,
            provider_name=call.provider_name,
            location_name=call.location_name,
        )
    )
    result_url = f"{base}/confirmation/result?cid={call.confirmation_id}&attempt={attempt}"
    gather = _gather(result_url, locale, say)
    noresult = f"{base}/confirmation/noresult?cid={call.confirmation_id}"
    return twiml_response(gather + f'<Redirect method="POST">{escape(noresult)}</Redirect>')


def twiml_say(text: str, language: str) -> str:
    locale = twilio_locale(language)
    return twiml_response(f'<Say language="{locale}">{escape(text)}</Say>')


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
        self, call: ConfirmationCall, base_url: str, *, attempt: int, reprompt: bool
    ) -> str: ...

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
        self, call: ConfirmationCall, base_url: str, *, attempt: int, reprompt: bool
    ) -> str:
        return twiml_ask(call, base_url, attempt=attempt, reprompt=reprompt)

    def classify(self, transcript: str, language: str) -> CallOutcome:
        return classify_reply(transcript, language)

    def ack(self, outcome: CallOutcome, language: str) -> str:
        return ack_text(outcome, language)

    def final_unclear(self, language: str) -> str:
        return final_unclear_text(language)

    def no_speech(self, language: str) -> str:
        return no_speech_text(language)


register_job(AppointmentConfirmationJob())


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
    status: ConfirmationStatus = "pending"
    detail: str = ""
    twilio_call_sid: str = ""
    transcript: str = ""
    attempts: int = 0
    # Twilio-only rebooking (no live voice pipeline): the slots the call
    # offered, as a JSON list, and the start the patient picked, ISO-8601.
    offered_slots: str = ""
    rescheduled_to: str = ""

    @property
    def appointment_dt(self) -> datetime:
        return datetime.fromisoformat(self.appointment_at)

    @property
    def call_dt(self) -> datetime:
        return datetime.fromisoformat(self.call_at)


def default_calls_path(settings: Settings) -> Path:
    return settings.calls_log_path.with_name("confirmation_calls.json")


def confirmation_store_from_settings(settings: Settings) -> ConfirmationStore:
    path = (
        Path(settings.confirmation_calls_path)
        if settings.confirmation_calls_path
        else default_calls_path(settings)
    )
    return ConfirmationStore(path)


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
                out.append(ConfirmationCall(**row))
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
            rows = [
                row
                for row in rows
                if not (
                    row.status == "pending"
                    and row.to == call.to
                    and row.appointment_at == call.appointment_at
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
            now_aware = now if now.tzinfo is not None else now.replace(tzinfo=MADRID)
            for row in rows:
                if row.status != "pending":
                    continue
                try:
                    call_at = row.call_dt
                except ValueError:
                    row.status = "skipped"
                    row.detail = "bad_call_at"
                    continue
                if call_at.tzinfo is None:
                    call_at = call_at.replace(tzinfo=MADRID)
                if call_at <= now_aware:
                    row.status = "calling"
                    row.detail = "claimed"
                    due.append(ConfirmationCall(**asdict(row)))
            if due:
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
    now: datetime | None = None,
    lead: timedelta | None = None,
) -> ConfirmationCall | None:
    """Return a pending call for ``when - lead``, or ``None`` when that is past."""
    if when.tzinfo is None:
        raise ValueError(f"appointment datetime must carry an offset: {when.isoformat()}")
    clock = now or datetime.now(tz=MADRID)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=MADRID)
    if when - clock < MIN_BOOKING_GAP:
        return None
    gap = lead if lead is not None else timedelta(days=1)
    call_at = job_for(job).call_at(when=when, lead=gap)
    if call_at <= clock:
        return None
    return ConfirmationCall(
        confirmation_id=uuid.uuid4().hex,
        job=job,
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
    now: datetime | None = None,
    lead: timedelta | None = None,
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
