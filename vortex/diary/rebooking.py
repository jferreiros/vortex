"""Post-call rebooking queue for requests that missed their first window.

This is deliberately outside the live phone-call submission path. A platform
submission is tied to one ``call_id`` and its 30-second window, so a later slot
reopening becomes an ops draft, not a delayed ``submit_action`` for the old call.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from vortex.clinic.client import ClinicApi
from vortex.contract import BookAction, RescheduleAction, Slot

RebookingIntent = Literal["book", "reschedule"]
RebookingStatus = Literal["pending", "matched"]
DraftAction = BookAction | RescheduleAction

_DEFAULT_POLICY = "privado"

_RESCHEDULE_WORDS = re.compile(
    r"\b("
    r"reschedul\w*|move|moved|moving|change|changed|changing|"
    r"mover|mueve|cambiar|cambio|reprogram\w*|traslad\w*"
    r")\b",
    re.IGNORECASE,
)


class RebookingRequest(BaseModel):
    """A request we can re-check when availability changes."""

    request_id: str
    call_id: str
    intent: RebookingIntent = "book"
    status: RebookingStatus = "pending"
    patient_id: str
    policy_id: str = _DEFAULT_POLICY
    date_from: date
    date_to: date
    time_from: time | None = None
    time_to: time | None = None
    specialty_id: str | None = None
    provider_id: str | None = None
    location_id: str | None = None
    appointment_id: str | None = None
    source_reason: str = "no_availability"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    matched_slot: Slot | None = None
    draft_action: DraftAction | None = None


class _Search(BaseModel):
    args: dict[str, Any]
    result: dict[str, Any]


def analyze_call(events: Sequence[dict[str, Any]]) -> RebookingRequest | None:
    """Extract one pending rebooking from a completed no-availability call.

    The source of truth is the event log the call already wrote. We only queue
    calls that ended by submitting ``NO_ACTION(no_availability)`` and whose last
    failed slot search still contains the API-derived ids needed to try again.
    """

    call_id = _call_id(events)
    if not call_id or _last_submitted_action(events) != ("no-action", "no_availability"):
        return None

    search = _last_no_availability_search(events)
    if search is None:
        return None

    args = search.args
    patient_id = str(args.get("patient_id") or _last_patient_id(events) or "")
    if not patient_id:
        return None
    if not (args.get("provider_id") or args.get("specialty_id")):
        return None

    policy_id = _policy_id(events, patient_id, args)
    intent: RebookingIntent = "reschedule" if _looks_like_reschedule(events) else "book"
    appointment_id = (
        _appointment_id_for_search(events, args, patient_id)
        if intent == "reschedule"
        else None
    )
    if intent == "reschedule" and not appointment_id:
        intent = "book"

    payload = {
        "call_id": call_id,
        "intent": intent,
        "patient_id": patient_id,
        "appointment_id": appointment_id,
        "provider_id": _optional_str(args.get("provider_id")),
        "specialty_id": _optional_str(args.get("specialty_id")),
        "location_id": _optional_str(args.get("location_id")),
        "date_from": _parse_date(args["date_from"]),
        "date_to": _parse_date(args["date_to"]),
        "time_from": _parse_time(args.get("time_from")),
        "time_to": _parse_time(args.get("time_to")),
        "policy_id": policy_id,
    }
    request_id = _stable_id(payload)
    return RebookingRequest(request_id=request_id, source_reason="no_availability", **payload)


def analyze_calls(events: Iterable[dict[str, Any]]) -> list[RebookingRequest]:
    """Extract queueable requests from many call events."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(str(event.get("call_id") or "?"), []).append(event)
    return [request for call in grouped.values() if (request := analyze_call(call)) is not None]


def analyze_latest_call(events: Iterable[dict[str, Any]]) -> RebookingRequest | None:
    """Extract a queueable request from the most recent call in an event stream."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for event in events:
        call_id = str(event.get("call_id") or "?")
        if call_id not in grouped:
            order.append(call_id)
            grouped[call_id] = []
        grouped[call_id].append(event)
    if not order:
        return None
    return analyze_call(grouped[order[-1]])


class RebookingStore:
    """SQLite-backed queue, safe to recreate whenever the process starts."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rebooking_requests (
                    request_id TEXT PRIMARY KEY,
                    call_id TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    status TEXT NOT NULL,
                    patient_id TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    date_from TEXT NOT NULL,
                    date_to TEXT NOT NULL,
                    time_from TEXT,
                    time_to TEXT,
                    specialty_id TEXT,
                    provider_id TEXT,
                    location_id TEXT,
                    appointment_id TEXT,
                    source_reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    matched_slot_json TEXT,
                    draft_action_json TEXT
                )
                """
            )

    def add(self, request: RebookingRequest) -> RebookingRequest:
        """Insert once and return the stored row, making log re-analysis idempotent."""

        data = request.model_dump(mode="json")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO rebooking_requests (
                    request_id, call_id, intent, status, patient_id, policy_id,
                    date_from, date_to, time_from, time_to, specialty_id, provider_id,
                    location_id, appointment_id, source_reason, created_at, updated_at,
                    matched_slot_json, draft_action_json
                )
                VALUES (
                    :request_id, :call_id, :intent, :status, :patient_id, :policy_id,
                    :date_from, :date_to, :time_from, :time_to, :specialty_id, :provider_id,
                    :location_id, :appointment_id, :source_reason, :created_at, :updated_at,
                    :matched_slot_json, :draft_action_json
                )
                """,
                {
                    **data,
                    "matched_slot_json": _json_or_none(data.get("matched_slot")),
                    "draft_action_json": _json_or_none(data.get("draft_action")),
                },
            )
        stored = self.get(request.request_id)
        assert stored is not None
        return stored

    def get(self, request_id: str) -> RebookingRequest | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM rebooking_requests WHERE request_id = ?", (request_id,)
            ).fetchone()
        return _row_to_request(row) if row is not None else None

    def pending(self) -> list[RebookingRequest]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM rebooking_requests
                WHERE status = 'pending'
                ORDER BY created_at, request_id
                """
            ).fetchall()
        return [_row_to_request(row) for row in rows]

    def all(self) -> list[RebookingRequest]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM rebooking_requests ORDER BY created_at, request_id"
            ).fetchall()
        return [_row_to_request(row) for row in rows]

    def mark_matched(
        self, request_id: str, *, slot: Slot, draft_action: DraftAction
    ) -> RebookingRequest:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE rebooking_requests
                SET status = 'matched',
                    updated_at = ?,
                    matched_slot_json = ?,
                    draft_action_json = ?
                WHERE request_id = ?
                """,
                (
                    now,
                    slot.model_dump_json(),
                    draft_action.model_dump_json(),
                    request_id,
                ),
            )
        stored = self.get(request_id)
        assert stored is not None
        return stored


class RebookingWatcher:
    """Re-check pending queue entries and draft actions when a slot reappears."""

    def __init__(self, clinic: ClinicApi, store: RebookingStore):
        self.clinic = clinic
        self.store = store

    async def check_once(self) -> list[RebookingRequest]:
        matched: list[RebookingRequest] = []
        for request in self.store.pending():
            answer = await self.clinic.availability(
                date_from=request.date_from,
                date_to=request.date_to,
                provider_id=request.provider_id,
                specialty_id=request.specialty_id,
                location_id=request.location_id,
                patient_id=request.patient_id,
                insurer=[request.policy_id] if request.policy_id else None,
            )
            slots = _filter_time(answer.slots, request)
            if not slots:
                continue
            slot = slots[0]
            action = _draft_action(request, slot)
            matched.append(
                self.store.mark_matched(request.request_id, slot=slot, draft_action=action)
            )
        return matched


def _draft_action(request: RebookingRequest, slot: Slot) -> DraftAction:
    if request.intent == "reschedule" and request.appointment_id:
        return RescheduleAction(
            appointment_id=request.appointment_id,
            provider_id=slot.provider_id,
            location_id=slot.location_id,
            slot=slot.start,
            policy_id=request.policy_id,
        )
    return BookAction(
        patient_id=request.patient_id,
        provider_id=slot.provider_id,
        location_id=slot.location_id,
        appointment_type_id=slot.appointment_type_id,
        slot=slot.start,
        policy_id=request.policy_id,
    )


def _filter_time(slots: list[Slot], request: RebookingRequest) -> list[Slot]:
    def keep(slot: Slot) -> bool:
        local_time = slot.start.timetz().replace(tzinfo=None)
        if request.time_from and local_time < request.time_from:
            return False
        if request.time_to and local_time >= request.time_to:
            return False
        return True

    return sorted((slot for slot in slots if keep(slot)), key=lambda s: (s.start, s.provider_id))


def _call_id(events: Sequence[dict[str, Any]]) -> str:
    return str(next((event.get("call_id") for event in events if event.get("call_id")), ""))


def _last_submitted_action(events: Sequence[dict[str, Any]]) -> tuple[str, str] | None:
    action: tuple[str, str] | None = None
    for event in events:
        kind = event.get("kind")
        if kind == "call.summary":
            actions = event.get("actions")
            if isinstance(actions, list) and actions:
                last = actions[-1]
                if isinstance(last, dict):
                    action = _action_tuple(last.get("route"), last.get("payload"))
        elif kind in {"submit.sent", "submit.result"}:
            action = _action_tuple(event.get("route"), event.get("payload"))
    return action


def _action_tuple(route: Any, payload: Any) -> tuple[str, str] | None:
    if not isinstance(route, str) or not isinstance(payload, dict):
        return None
    kind = route.rstrip("/").rsplit("/", 1)[-1]
    return kind, str(payload.get("reason") or "")


def _last_no_availability_search(events: Sequence[dict[str, Any]]) -> _Search | None:
    open_calls: list[dict[str, Any]] = []
    found: _Search | None = None
    for event in events:
        if event.get("kind") == "tool.called" and event.get("tool") == "find_slots":
            args = event.get("args")
            open_calls.append(args if isinstance(args, dict) else {})
        elif event.get("kind") == "tool.returned" and event.get("tool") == "find_slots":
            args = open_calls.pop() if open_calls else {}
            result = event.get("result")
            if isinstance(result, dict) and _is_no_availability(result):
                found = _Search(args=args, result=result)
    return found


def _is_no_availability(result: dict[str, Any]) -> bool:
    rejection = result.get("rejection")
    return isinstance(rejection, dict) and rejection.get("reason") == "no_availability"


def _last_patient_id(events: Sequence[dict[str, Any]]) -> str:
    for event in reversed(events):
        if event.get("kind") != "tool.returned":
            continue
        result = event.get("result")
        if not isinstance(result, dict):
            continue
        patient = result.get("patient")
        if isinstance(patient, dict) and patient.get("patient_id"):
            return str(patient["patient_id"])
    return ""


def _policy_id(events: Sequence[dict[str, Any]], patient_id: str, args: dict[str, Any]) -> str:
    if args.get("insurer"):
        return str(args["insurer"])
    for event in reversed(events):
        result = event.get("result")
        if not isinstance(result, dict):
            continue
        patient = result.get("patient")
        if (
            isinstance(patient, dict)
            and patient.get("patient_id") == patient_id
            and patient.get("insurer")
        ):
            return str(patient["insurer"])
    return _DEFAULT_POLICY


def _looks_like_reschedule(events: Sequence[dict[str, Any]]) -> bool:
    words = " ".join(
        str(event.get("text") or "") for event in events if event.get("kind") == "turn.user"
    )
    return bool(_RESCHEDULE_WORDS.search(words))


def _appointment_id_for_search(
    events: Sequence[dict[str, Any]], args: dict[str, Any], patient_id: str
) -> str | None:
    provider_id = _optional_str(args.get("provider_id"))
    location_id = _optional_str(args.get("location_id"))
    for event in reversed(events):
        if event.get("kind") != "tool.returned" or event.get("tool") != "list_appointments":
            continue
        result = event.get("result")
        appointments = result.get("appointments") if isinstance(result, dict) else None
        if not isinstance(appointments, list):
            continue
        for appointment in appointments:
            if not isinstance(appointment, dict) or appointment.get("patient_id") != patient_id:
                continue
            if provider_id and appointment.get("provider_id") != provider_id:
                continue
            if location_id and appointment.get("location_id") != location_id:
                continue
            return str(appointment.get("appointment_id") or "")
    return None


def _row_to_request(row: sqlite3.Row) -> RebookingRequest:
    data = dict(row)
    if data.get("matched_slot_json"):
        data["matched_slot"] = json.loads(data.pop("matched_slot_json"))
    else:
        data.pop("matched_slot_json", None)
    if data.get("draft_action_json"):
        data["draft_action"] = json.loads(data.pop("draft_action_json"))
    else:
        data.pop("draft_action_json", None)
    return RebookingRequest.model_validate(data)


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True)


def _stable_id(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return "rq_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _parse_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value))


def _parse_time(value: Any) -> time | None:
    if value in (None, ""):
        return None
    if isinstance(value, time):
        return value
    return time.fromisoformat(str(value))


def _optional_str(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None
