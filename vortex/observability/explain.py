"""Turn a call's events into sentences a judge can read in ten seconds.

The console must answer "what is the agent doing" and "why did it do that".
This module holds the vocabulary: one sentence per decline reason, one label
per action, the four stages of a call, and the summary numbers for a set of
calls. Pure functions over ``CallCard``; no UI here.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any

from vortex.observability.view import CallCard, ToolStep

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

#: What each submitted action means, in the platform's own words.
ACTION_LABEL: dict[str, str] = {
    "book": "Booked",
    "register": "Registered",
    "reschedule": "Rescheduled",
    "cancel": "Cancelled",
    "no-action": "No action",
    "escalate": "Escalated",
}

#: Call status (``CallCard.status``) to a short label.
STATUS_LABEL: dict[str, str] = {
    "live": "Live",
    "booked": "Booked",
    "registered": "Registered",
    "rescheduled": "Rescheduled",
    "cancelled": "Cancelled",
    "refused": "No action",
    "escalated": "Escalated",
    "ended": "Ended",
}

#: One plain sentence per decline reason. The reason is what we submit; the
#: sentence is what the wall shows next to it.
REASON_TEXT: dict[str, str] = {
    "not_eligible_age": "The patient's age is outside the range this specialty accepts.",
    "referral_required": "This specialty needs a referral and the patient has none on file.",
    "provider_not_in_network": "The requested doctor is not in the patient's insurance network.",
    "specialty_not_covered": "The patient's insurance does not cover this specialty here.",
    "location_not_covered": "The patient's insurance does not cover this site.",
    "insurer_referral_required": "The insurer requires a referral before this visit.",
    "allowance_exhausted": "The patient has used up this year's allowance for this visit type.",
    "provider_on_leave": "The requested doctor is on leave for the dates asked.",
    "location_hours": "The site is closed at the time requested.",
    "type_not_offered": "This site does not offer that appointment type.",
    "patient_history": "The patient's history rules this visit out.",
    "no_availability": "No slot matched the request in the window asked.",
    "clinic_closed": "The clinic is closed on the day requested.",
    "patient_not_found": "No patient in the directory matched the caller's details.",
    "provider_not_found": "No doctor at the clinic matched the name given.",
    "caller_not_authorised": "The caller is not allowed to act for this patient.",
    "out_of_scope": "The request is outside what the clinic line handles.",
    "medical_emergency": "The symptoms described need emergency care, not an appointment.",
}

#: Reasons that name a clinic rule, as opposed to a lookup that found nothing.
RULE_REASONS: frozenset[str] = frozenset(
    {
        "not_eligible_age",
        "referral_required",
        "provider_not_in_network",
        "specialty_not_covered",
        "location_not_covered",
        "insurer_referral_required",
        "allowance_exhausted",
        "provider_on_leave",
        "location_hours",
        "type_not_offered",
        "patient_history",
    }
)

#: What each tool does, for the decision timeline.
TOOL_TEXT: dict[str, str] = {
    "find_patient": "Look the caller up in the clinic directory",
    "validate_national_id": "Check the DNI/NIE control letter",
    "build_registration": "Build a new patient record",
    "find_provider": "Match the doctor's name to a provider",
    "resolve_date": "Turn a spoken date into an exact minute in Madrid",
    "check_eligibility": "Check the clinic's rules and the insurance matrix",
    "find_slots": "Search availability at the clinic",
    "list_appointments": "Read the patient's upcoming appointments",
    "prepare_booking": "Build the exact booking to submit",
    "prepare_reschedule": "Move an existing appointment",
    "prepare_cancel": "Cancel an existing appointment",
    "triage": "Route the symptom to a specialty",
    "nearest_location": "Pick the closest clinic site",
    "submit_action": "Send the action to the platform",
}

# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------

STAGES: tuple[tuple[str, str, str], ...] = (
    ("listen", "Listen", "The platform dials our socket and plays a patient."),
    ("identify", "Identify", "We find the caller in the read-only directory."),
    ("decide", "Decide", "Rules, insurance and availability pick one action."),
    ("submit", "Submit", "One POST to the platform inside the 30-second window."),
)

_IDENTIFY_TOOLS = {"find_patient", "validate_national_id", "build_registration"}
_DECIDE_TOOLS = {
    "find_provider",
    "resolve_date",
    "check_eligibility",
    "find_slots",
    "list_appointments",
    "prepare_booking",
    "prepare_reschedule",
    "prepare_cancel",
    "triage",
    "nearest_location",
}


def stage_of(card: CallCard | None) -> int:
    """0..4: how far the call got. 4 means submitted."""
    if card is None:
        return 0
    if card.submit_status or card.submit_route:
        return 4
    names = {t.name for t in card.tools}
    if names & _DECIDE_TOOLS:
        return 3
    if names & _IDENTIFY_TOOLS:
        return 2
    if card.turns:
        return 1
    return 0


# ---------------------------------------------------------------------------
# Sentences
# ---------------------------------------------------------------------------


def reason_text(reason: str | None) -> str:
    if not reason:
        return ""
    return REASON_TEXT.get(reason, reason.replace("_", " ").capitalize() + ".")


def submitted(card: CallCard) -> bool:
    """True when the platform was actually sent something."""
    return bool(card.submit_status or card.submit_route)


def status_label(card: CallCard) -> str:
    """The word for a call in a list or a pill. An action that was prepared
    but never sent is not an outcome; it reads as Ended."""
    if not card.live and card.action_kind and not submitted(card):
        return "Ended"
    return STATUS_LABEL.get(card.status, card.status)


def outcome_title(card: CallCard | None) -> str:
    """The headline of the outcome card."""
    if card is None:
        return "Waiting for a call"
    if card.live:
        return "On a call"
    if card.action_kind and submitted(card):
        return ACTION_LABEL.get(card.action_kind, card.action_kind)
    return "Ended without a submission"


def outcome_text(card: CallCard | None) -> str:
    """One sentence under the headline: what happened and why."""
    if card is None:
        return "The line is up. The next inbound call appears here."
    if card.live:
        stage = stage_of(card)
        return STAGES[max(stage - 1, 0)][2]
    kind = card.action_kind if submitted(card) else None
    if card.action_kind and kind is None:
        return "The agent prepared an action but the socket closed before it was sent."
    if kind == "book":
        who = card.patient_name or "the patient"
        when = card.slot or "the requested slot"
        doc = f" with {card.provider_name}" if card.provider_name else ""
        return f"Appointment for {who}{doc} at {when}, submitted to the platform."
    if kind == "register":
        return "New patient created from the details given on the call. Nothing booked."
    if kind == "reschedule":
        return "The existing appointment was moved to the new slot."
    if kind == "cancel":
        return "The existing appointment was cancelled at the caller's request."
    if kind in {"no-action", "escalate"}:
        return reason_text(card.decline_reason) or "The call ended with a typed refusal."
    return "The socket closed before any action was submitted."


def step_text(step: ToolStep) -> str:
    """One line per tool step: what came back, in words."""
    if step.status == "running":
        return "Running…"
    if step.status == "fail":
        return f"Failed: {step.error or 'unknown error'}"
    data = step.result if isinstance(step.result, dict) else {}
    if step.name == "find_patient":
        status = data.get("status")
        patient = data.get("patient") if isinstance(data.get("patient"), dict) else {}
        if status == "found" and patient:
            name = " ".join(
                p
                for p in (
                    patient.get("given_name"),
                    patient.get("first_surname"),
                    patient.get("second_surname"),
                )
                if p
            )
            insurer = patient.get("insurer")
            tail = f" · {insurer}" if insurer else ""
            return f"Found {name} ({patient.get('patient_id', '?')}){tail}"
        if status == "ambiguous":
            return "Several patients match. Asking for a second field."
        return "Not found in the directory."
    if step.name == "check_eligibility":
        if data.get("allowed"):
            return "Allowed by the clinic rules and the insurance matrix."
        rejection = data.get("rejection") if isinstance(data.get("rejection"), dict) else {}
        reason = rejection.get("reason") or "rejected"
        detail = rejection.get("detail")
        return f"Rejected: {reason}" + (f" — {detail}" if detail else "")
    if step.name == "find_slots":
        slots = data.get("slots") if isinstance(data.get("slots"), list) else []
        blocked = data.get("blocked") if isinstance(data.get("blocked"), list) else []
        if slots:
            first = slots[0] if isinstance(slots[0], dict) else {}
            return f"{len(slots)} slot(s) free. First: {first.get('start', '?')}"
        if blocked:
            return f"No slot free. {len(blocked)} blocked by a rule."
        return "No slot free in the window asked."
    if step.name in {"prepare_booking", "prepare_reschedule", "prepare_cancel"}:
        action = data.get("action") if isinstance(data.get("action"), dict) else None
        if action:
            kind = str(action.get("kind", ""))
            return f"Ready to submit: {ACTION_LABEL.get(kind, kind)}"
        rejection = data.get("rejection") if isinstance(data.get("rejection"), dict) else {}
        if rejection:
            return f"Rejected: {rejection.get('reason', '?')}"
        return "Done."
    if step.name == "build_registration":
        return "Registration action built."
    if step.name == "triage":
        specialty = data.get("specialty") or data.get("specialty_id")
        if data.get("red_flag") or data.get("emergency"):
            return "Red flag: this is an emergency."
        return f"Routed to {specialty}." if specialty else "Routed."
    keys = ", ".join(str(k) for k in list(data)[:4])
    return keys or "Done."


def tool_description(name: str) -> str:
    return TOOL_TEXT.get(name, name.replace("_", " ").capitalize())


#: Which clinic endpoint each tool hits. Same map as scripts/call_rundown.py.
TOOL_ENDPOINT: dict[str, str] = {
    "find_patient": "GET /api/v1/directory · +GET /patients/{id}/appointments?when=past",
    "validate_national_id": "local · DNI/NIE check letter",
    "build_registration": "GET /api/v1/clinic",
    "resolve_date": "GET /api/v1/clinic",
    "find_slots": "GET /api/v1/availability",
    "list_appointments": "GET /patients/{id}/appointments",
    "prepare_booking": "GET /api/v1/clinic + GET /api/v1/availability",
    "prepare_reschedule": "GET /patients/{id}/appointments + /availability",
    "prepare_cancel": "GET /patients/{id}/appointments",
    "check_eligibility": "GET /api/v1/availability + GET /api/v1/clinic",
    "triage": "local · symptom rules",
    "nearest_location": "local · site distances",
    "find_provider": "GET /api/v1/clinic",
    "submit_action": "POST /api/v1/submit/<route>",
}


def tool_endpoint(name: str) -> str | None:
    return TOOL_ENDPOINT.get(name)


#: The lines of a call that are neither a turn nor a tool call, in words.
EVENT_TEXT: dict[str, str] = {
    "call.started": "The socket opened and a fresh pipeline started.",
    "submit.sent": "Posted the action to the platform.",
    "submit.result": "The platform answered the submission.",
    "call.ended": "The socket closed.",
    "call.summary": "The call was summarised.",
    "call.crashed": "The pipeline crashed.",
}


def is_lifecycle(event: dict[str, Any]) -> bool:
    """True for the socket, submission and summary lines; false for turns and tools."""
    kind = str(event.get("kind") or "")
    return not (kind.startswith("turn.") or kind.startswith("tool."))


def event_text(event: dict[str, Any]) -> str:
    kind = str(event.get("kind") or "")
    return EVENT_TEXT.get(kind, kind.replace(".", " ").capitalize() or "Event")


def event_detail(event: dict[str, Any]) -> str:
    """The facts on the line, in one string: route, status, reason, frames, error."""
    kind = str(event.get("kind") or "")
    bits: list[str] = []
    for key in ("voice", "clinic", "route", "reason", "why"):
        value = event.get(key)
        if value:
            bits.append(f"{key} {value}")
    result = event.get("result")
    if isinstance(result, dict):
        for key in ("status", "http_status", "detail"):
            if result.get(key):
                bits.append(f"{key} {result[key]}")
    if kind == "call.ended":
        frames_in = event.get("media_frames_in", "?")
        frames_out = event.get("media_frames_out", "?")
        bits.append(f"frames in {frames_in}, out {frames_out}")
    if kind == "call.summary" and event.get("duration_ms") is not None:
        bits.append(f"{event['duration_ms']} ms")
    if kind == "call.crashed" and event.get("error"):
        bits.append(str(event["error"])[:120])
    return " · ".join(bits)


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------


@dataclass
class Stats:
    calls: int = 0
    live: int = 0
    booked: int = 0
    refused: int = 0
    escalated: int = 0
    other_actions: int = 0
    submitted: int = 0
    median_duration_s: float | None = None
    median_tool_ms: float | None = None
    top_reason: str | None = None

    @property
    def submit_rate(self) -> float | None:
        ended = self.calls - self.live
        return None if ended <= 0 else self.submitted / ended


def stats_for(cards: list[CallCard]) -> Stats:
    stats = Stats(calls=len(cards))
    durations: list[float] = []
    tool_ms: list[float] = []
    reasons: dict[str, int] = {}
    for card in cards:
        if card.live:
            stats.live += 1
            continue
        status = card.status
        if status == "booked":
            stats.booked += 1
        elif status == "refused":
            stats.refused += 1
        elif status == "escalated":
            stats.escalated += 1
        elif status in {"registered", "rescheduled", "cancelled"}:
            stats.other_actions += 1
        if card.submit_status or card.submit_route:
            stats.submitted += 1
        if card.duration_ms:
            durations.append(card.duration_ms / 1000)
        for step in card.tools:
            if step.ms is not None:
                tool_ms.append(step.ms)
        if card.decline_reason:
            reasons[card.decline_reason] = reasons.get(card.decline_reason, 0) + 1
    if durations:
        stats.median_duration_s = median(durations)
    if tool_ms:
        stats.median_tool_ms = median(tool_ms)
    if reasons:
        stats.top_reason = max(reasons, key=lambda r: reasons[r])
    return stats


def payload_rows(card: CallCard) -> list[tuple[str, Any]]:
    """The submitted payload as label/value rows, ids first, call_id last."""
    payload = card.action_payload or {}
    order = (
        "patient_id",
        "provider_id",
        "location_id",
        "appointment_type_id",
        "slot",
        "policy_id",
        "appointment_id",
        "new_slot",
        "reason",
    )
    rows: list[tuple[str, Any]] = []
    for key in order:
        if key in payload and payload[key] not in (None, ""):
            rows.append((key, payload[key]))
    for key, value in payload.items():
        if key not in order and key != "call_id" and value not in (None, ""):
            rows.append((key, value))
    return rows
