"""THE FROZEN TOOL CONTRACT.

This is the one file the five lanes agree on. It holds:

1. The closed vocabulary of decline reasons (call contract §3).
2. The six submission actions and their exact payloads (call contract §3).
3. The typed records the clinic API returns (patients, providers, slots ...).
4. The input and output model of every tool a lane implements.
5. The frozen signature of every tool, as a ``Protocol``.
6. A stub implementation of every tool. Stubs return fake but well-formed data.

Rules for this file:

- Do not change a signature, a field name or a field type without telling the
  whole team. Adding an optional field is fine. Renaming is not.
- Every tool returns typed data or a typed ``Rejection``. Never prose for the
  model to interpret.
- Every tool is ``async`` and takes ``(ctx: ToolContext, args: <Input>)``.
- The lane owner replaces the ``stub_*`` call inside ``vortex/<lane>/tools.py``.
  Nobody edits the stubs here; they are the reference shape.

Time rules that every lane shares:

- ``ToolContext.now`` is the moment the call connected, tz-aware, Europe/Madrid.
- Every ``datetime`` that crosses a tool boundary is tz-aware.
- ``slot`` values carry an explicit offset and match the platform to the minute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, Literal, Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids an import cycle
    from vortex.clinic.client import ClinicApi
    from vortex.line.submit import SubmitApi
    from vortex.observability.calllog import CallLog

MADRID = ZoneInfo("Europe/Madrid")

# ---------------------------------------------------------------------------
# 1. Decline reasons (closed vocabulary, call contract §3)
# ---------------------------------------------------------------------------

# The first eleven mirror the clinic's own restrictions one-for-one.
RULE_REASONS: tuple[str, ...] = (
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
)

# The rest cover endings that are not about a clinic rule.
OTHER_REASONS: tuple[str, ...] = (
    "no_availability",
    "clinic_closed",
    "patient_not_found",
    "provider_not_found",
    "caller_not_authorised",
    "out_of_scope",
    "medical_emergency",
)

ALL_REASONS: tuple[str, ...] = RULE_REASONS + OTHER_REASONS

#: The ``Insurer`` enum of the platform schema, in its published order. The
#: platform validates ``insurer`` and ``policy_id`` against exactly these ten
#: values (422 otherwise), and ``/availability?insurer=`` against them too.
#: Kept as data, not as a field type: a plan we cannot name must still reach the
#: platform so the rejection is theirs to explain, not a local ValidationError
#: in the middle of a call.
INSURERS: tuple[str, ...] = (
    "sanitas",
    "adeslas",
    "dkv",
    "asisa",
    "mapfre",
    "caser",
    "cigna",
    "axa",
    "nueva_mutua",
    "privado",
)

DeclineReason = Literal[
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
    "no_availability",
    "clinic_closed",
    "patient_not_found",
    "provider_not_found",
    "caller_not_authorised",
    "out_of_scope",
    "medical_emergency",
]


class Rejection(BaseModel):
    """A typed refusal. ``reason`` is what we submit; ``detail`` is for the log."""

    reason: DeclineReason
    detail: str = ""


# ---------------------------------------------------------------------------
# 2. Submission actions (call contract §3) - one route per action
# ---------------------------------------------------------------------------


def _aware_slot(value: datetime) -> datetime:
    """``slot`` must serialise with an explicit offset or the platform 422s.

    A naive datetime can only ever have meant clinic time, so it is read as
    Europe/Madrid rather than allowed out of the door without an offset.
    """
    return value.replace(tzinfo=MADRID) if value.tzinfo is None else value


class BookAction(BaseModel):
    kind: Literal["book"] = "book"
    patient_id: str
    provider_id: str
    location_id: str
    appointment_type_id: str
    slot: datetime  # tz-aware; serialised with its offset
    policy_id: str  # one of INSURERS

    _slot_offset = field_validator("slot")(_aware_slot)


class RegisterAction(BaseModel):
    kind: Literal["register"] = "register"
    given_name: str
    first_surname: str
    second_surname: str
    national_id: str  # DNI/NIE with its check letter
    date_of_birth: date
    phone: str
    email: str
    insurer: str  # one of INSURERS


class RescheduleAction(BaseModel):
    kind: Literal["reschedule"] = "reschedule"
    appointment_id: str
    provider_id: str
    location_id: str
    slot: datetime
    policy_id: str  # one of INSURERS

    _slot_offset = field_validator("slot")(_aware_slot)


class CancelAction(BaseModel):
    kind: Literal["cancel"] = "cancel"
    appointment_id: str


class NoAction(BaseModel):
    kind: Literal["no-action"] = "no-action"
    reason: DeclineReason


class EscalateAction(BaseModel):
    kind: Literal["escalate"] = "escalate"
    reason: DeclineReason


Action = BookAction | RegisterAction | RescheduleAction | CancelAction | NoAction | EscalateAction

ACTION_ROUTES: dict[str, str] = {
    "book": "/api/v1/submit/book",
    "register": "/api/v1/submit/register",
    "reschedule": "/api/v1/submit/reschedule",
    "cancel": "/api/v1/submit/cancel",
    "no-action": "/api/v1/submit/no-action",
    "escalate": "/api/v1/submit/escalate",
}


def action_route(action: Action) -> str:
    return ACTION_ROUTES[action.kind]


def action_payload(action: Action, call_id: str) -> dict[str, Any]:
    """The JSON body for the submit route: snake_case, ``call_id`` first."""
    body = action.model_dump(mode="json", exclude={"kind"})
    return {"call_id": call_id, **body}


# ---------------------------------------------------------------------------
# 3. Clinic records. These are *our* shape, not the platform's: the adapters in
#    ``vortex/clinic/client.py`` translate every payload into them, which is the
#    one place a platform field name appears. Checked against
#    ``docs/platform/openapi.json`` and against live responses from every
#    read-only route on 18 Sep 2026. ``extra="allow"`` keeps a field the
#    platform adds later instead of failing the call on it.
#
#    Where a name differs from the platform's, the platform's is in a comment.
# ---------------------------------------------------------------------------


class _Record(BaseModel):
    model_config = ConfigDict(extra="allow")


class PatientRecord(_Record):
    """One ``PatientMatchOut`` from ``GET /api/v1/directory``."""

    patient_id: str
    given_name: str
    first_surname: str
    second_surname: str = ""
    national_id: str = ""
    date_of_birth: date | None = None
    phone: str = ""
    #: The directory does **not** return an email. It stays here because
    #: registration collects one on the call; on a looked-up patient it is "".
    email: str = ""
    sex: str = ""  # "M" or "F"
    insurer: str = ""  # the one plan on the record; a second one is never in the data
    has_visited_before: bool = False
    note: str = ""
    referrals: list[str] = Field(default_factory=list)  # specialty ids
    #: How the platform rated this match, and on which fields it matched.
    #: Both come back on every match; they are how two namesakes are told apart.
    match_score: float | None = None
    matched_fields: list[str] = Field(default_factory=list)

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.given_name, self.first_surname, self.second_surname) if p)


class OpeningHours(_Record):
    """One interval of one weekday. The platform sends ``"09:00–14:00"`` strings
    under a named weekday; a day that shuts for lunch becomes two of these."""

    weekday: int  # 0 = Monday ... 6 = Sunday
    opens: time
    closes: time


class LocationRecord(_Record):
    location_id: str  # platform: id
    name: str
    address: str = ""
    latitude: float | None = None
    longitude: float | None = None
    hours: list[OpeningHours] = Field(default_factory=list)
    provider_ids: list[str] = Field(default_factory=list)  # platform: provider_names
    insurer_ids: list[str] = Field(default_factory=list)  # platform: covered_by
    insurer_ids_excluded: list[str] = Field(default_factory=list)  # platform: not_covered_by


class SpecialtyRecord(_Record):
    specialty_id: str  # platform: id
    name: str
    min_age_months: int | None = None
    max_age_months: int | None = None
    referral_required: bool = False
    insurer_ids: list[str] = Field(default_factory=list)  # platform: covered_by
    insurer_ids_excluded: list[str] = Field(default_factory=list)  # platform: not_covered_by
    provider_ids: list[str] = Field(default_factory=list)  # platform: provider_names


class AppointmentTypeRecord(_Record):
    appointment_type_id: str  # platform: id
    name: str
    specialty_id: str | None = None  # None = universal (first_visit, review)
    duration_minutes: int = 15
    #: The platform's own word: "new_only" or "existing_only". Kept raw so a
    #: value we have not seen cannot silently become "either".
    new_patient_requirement: str = ""
    for_new_patients: bool | None = None  # None = either; derived from the above
    guidance: str = ""


class LeaveRecord(_Record):
    date_from: date  # platform: start
    date_to: date  # platform: end
    reason: str = ""


class ProviderSchedule(_Record):
    """When one provider sits at one site. The rule behind ``location_hours``."""

    location_id: str
    hours: list[OpeningHours] = Field(default_factory=list)


class ProviderRecord(_Record):
    provider_id: str  # platform: id
    name: str  # as submitted and as spoken, title included ("D. Álvaro Cid")
    specialty_id: str
    specialty_name: str = ""
    languages: list[str] = Field(default_factory=list)  # ISO-639-1: es, ca, en ...
    appointment_type_ids: list[str] = Field(default_factory=list)  # platform: *_names
    location_ids: list[str] = Field(default_factory=list)  # from schedules' location_id
    insurer_ids_accepted: list[str] = Field(default_factory=list)  # platform: accepted_insurers
    insurer_ids_refused: list[str] = Field(default_factory=list)  # platform: refused_insurers
    schedules: list[ProviderSchedule] = Field(default_factory=list)
    #: The platform sends at most one leave period, or null. A list keeps the
    #: door open for a second one without another contract change.
    leave: list[LeaveRecord] = Field(default_factory=list)


class InsurancePlanRecord(_Record):
    """One ``ClinicPlanResponse``. The platform states coverage both ways round;
    an empty ``*_excluded`` list means the plan excludes nothing, not unknown."""

    insurer_id: str  # platform: id
    name: str
    specialty_ids: list[str] = Field(default_factory=list)  # platform: covered_specialty_names
    specialty_ids_excluded: list[str] = Field(default_factory=list)  # uncovered_specialty_names
    location_ids: list[str] = Field(default_factory=list)  # platform: covered_location_names
    location_ids_excluded: list[str] = Field(default_factory=list)  # uncovered_location_names
    provider_ids: list[str] = Field(default_factory=list)  # platform: accepted_by
    provider_ids_refused: list[str] = Field(default_factory=list)  # platform: refused_by
    holders: int | None = None
    #: Ours, not the platform's: ``/clinic`` publishes neither, so on live data
    #: both stay at their defaults. The rules they would encode reach us as the
    #: ``insurer_referral_required`` and ``allowance_exhausted`` restrictions on
    #: ``/availability``'s ``blocked`` instead. Read them from there.
    referral_required: bool = False
    yearly_allowance: int | None = None


class RestrictionRecord(_Record):
    """A standing rule from GET /clinic, with the decline reason it carries.

    The platform's restriction ids *are* the eleven rule reasons, verbatim, and
    ``/availability``'s ``blocked[].restriction`` names one of them.
    """

    rule_id: str  # platform: id, and equal to ``reason``
    reason: DeclineReason
    description: str = ""  # platform: title
    explanation: str = ""  # the rule in the clinic's own words


class Catalogue(_Record):
    """Everything GET /api/v1/clinic returns. Fixed for the event; cache it."""

    clinic_name: str = ""
    patient_count: int | None = None
    locations: list[LocationRecord] = Field(default_factory=list)
    providers: list[ProviderRecord] = Field(default_factory=list)
    specialties: list[SpecialtyRecord] = Field(default_factory=list)
    appointment_types: list[AppointmentTypeRecord] = Field(default_factory=list)
    insurance_plans: list[InsurancePlanRecord] = Field(default_factory=list)  # platform: plans
    restrictions: list[RestrictionRecord] = Field(default_factory=list)
    # platform: calendar.{starts, ends, closure_days, max_span_days, slot_minutes}
    bookable_from: date | None = None
    bookable_to: date | None = None
    closure_days: list[date] = Field(default_factory=list)
    max_span_days: int = 14  # a wider /availability window is a 422
    slot_minutes: int = 15


class Slot(_Record):
    """One ``SlotOut``. Every field the platform sends is kept: the submitted
    ``appointment_type_id`` must be the one the slot carries."""

    start: datetime  # platform: start_time, tz-aware with an explicit offset
    provider_id: str
    provider_name: str = ""
    specialty_id: str = ""
    location_id: str
    appointment_type_id: str
    duration_minutes: int = 15
    #: Which of the queried plans covers this slot. **Empty unless the request
    #: passed ``insurer`` or ``patient_id``** - the platform only prices against
    #: plans it was asked about. An empty list is not "nothing covers it".
    payable_with: list[str] = Field(default_factory=list)


class BlockedProvider(_Record):
    provider_id: str
    #: The rule that stopped this provider, which is the reason we submit.
    reason: DeclineReason
    restriction: str = ""  # the platform's raw ``restriction`` id
    detail: str = ""


class AvailabilityProvider(_Record):
    """One ``ProviderOut`` from ``/availability``. Leaner than the catalogue's
    provider, and its ``locations``/``accepted_insurers`` are ids, not names."""

    provider_id: str  # platform: id
    name: str = ""
    specialty_id: str = ""
    languages: list[str] = Field(default_factory=list)
    insurer_ids_accepted: list[str] = Field(default_factory=list)  # platform: accepted_insurers
    location_ids: list[str] = Field(default_factory=list)  # platform: locations
    on_leave_until: str = ""


class AvailabilityResponse(_Record):
    providers: list[AvailabilityProvider] = Field(default_factory=list)
    slots: list[Slot] = Field(default_factory=list)
    blocked: list[BlockedProvider] = Field(default_factory=list)
    appointment_type: AppointmentTypeRecord | None = None


class Appointment(_Record):
    """One ``AppointmentOut``."""

    appointment_id: str
    patient_id: str
    provider_id: str
    location_id: str
    appointment_type_id: str
    start: datetime  # platform: start_time
    duration_minutes: int = 15
    #: Ours, not the platform's: ``AppointmentOut`` carries no status, so on
    #: live data this is always "scheduled". What can be cancelled or moved is
    #: what ``when=upcoming`` returns, not what this field says.
    status: str = "scheduled"


# ---------------------------------------------------------------------------
# 4. Tool context - what every tool receives besides its arguments
# ---------------------------------------------------------------------------


@dataclass
class ToolContext:
    """Per-call context. One instance per socket; never shared between calls."""

    call_id: str
    now: datetime  # moment the call connected, Europe/Madrid
    from_number: str | None
    clinic: ClinicApi
    log: CallLog
    # The call's submit client (line/). ``submit_action`` goes through it so a
    # submission always lands inside this call's 30-second window.
    submitter: SubmitApi | None = None
    # Free-form scratch space for the conversation: identified patient, chosen
    # slot, second policy ... Keys are the lane's choice. Keep it JSON-safe.
    state: dict[str, Any] = field(default_factory=dict)


#: Where every lane keeps the directory records this call has already fetched,
#: keyed by ``patient_id``. ``GET /api/v1/directory`` searches on ``name``,
#: ``national_id``, ``phone`` or ``date_of_birth`` and on nothing else — there
#: is no lookup by id — so a record can only come from a query somebody already
#: made. Identity's is the one every call makes, which is why it fills this.
PATIENT_RECORDS_KEY = "patients.by_id"


def remember_patient(ctx: ToolContext, record: PatientRecord) -> None:
    """Keep a directory record for the rest of this call. JSON-safe, per socket."""
    known = ctx.state.setdefault(PATIENT_RECORDS_KEY, {})
    known[record.patient_id] = record.model_dump(mode="json")


def recall_patient(ctx: ToolContext, patient_id: str) -> PatientRecord | None:
    """The record behind an id, if this call has already seen it."""
    raw = ctx.state.get(PATIENT_RECORDS_KEY, {}).get(patient_id)
    return PatientRecord.model_validate(raw) if raw else None


# ---------------------------------------------------------------------------
# 5. Tool inputs and outputs, lane by lane
# ---------------------------------------------------------------------------

# ---- identity/ -------------------------------------------------------------


class FindPatientInput(BaseModel):
    """Look a caller up. Fill only what the caller said. Empty = unknown."""

    name: str | None = Field(default=None, description="Name as heard, any order")
    national_id: str | None = Field(default=None, description="DNI/NIE as heard")
    phone: str | None = Field(default=None, description="Phone as heard or from caller id")
    date_of_birth: date | None = None


class FindPatientResult(BaseModel):
    status: Literal["found", "ambiguous", "not_found"]
    patient: PatientRecord | None = None
    candidates: list[PatientRecord] = Field(default_factory=list)
    # Which field to ask for next when ambiguous. Empty when found or not_found.
    ask_for: Literal["date_of_birth", "national_id", "phone", "name", ""] = ""


class CallerLineMatch(BaseModel):
    """Who the dialling line belongs to, resolved before the caller speaks.

    The directory takes a phone on its own, so the number Twilio hands us is a
    free exact query: one match names the line's owner, none says the line is on
    no record. It is a *hint about the line*, never an identification of the
    person holding it - the owner of the phone and the patient being booked for
    are different people on a third-party call.

    ``looked_up`` is False when there was no caller id, the lookup failed or it
    did not answer in time. The prompt renders no CALLER block for those, so the
    call behaves exactly as it did before the lookup existed.
    """

    looked_up: bool = False
    from_number: str = ""
    patient: PatientRecord | None = None
    #: Several records share the line (a family). Never one identity, so the
    #: prompt says nothing; the ordering hint still helps ``find_patient``.
    candidates: list[PatientRecord] = Field(default_factory=list)


class ValidateNationalIdInput(BaseModel):
    value: str = Field(description="DNI or NIE as heard, letters and digits")


class NationalIdCheck(BaseModel):
    normalized: str  # uppercase, no spaces or dashes; repaired id when uniquely corrected
    kind: Literal["dni", "nie", "invalid"]
    valid: bool  # the check letter matches the digits (of normalized)
    expected_letter: str | None = None
    # Heard form before a unique 1-edit digit repair. None when not repaired.
    repaired_from: str | None = None
    # 0-based indexes into the digit body to re-ask when several 1-edit
    # candidates fit the heard check letter. Empty otherwise.
    ask_digit_positions: list[int] = Field(default_factory=list)


class BuildRegistrationInput(BaseModel):
    given_name: str
    first_surname: str
    second_surname: str
    national_id: str
    date_of_birth: date
    #: Empty or absent means the line they are calling from. A new patient
    #: registers themselves, so the number they would dictate is the number
    #: Twilio already handed us, and a registration has eight fields to collect
    #: inside three minutes. ``build_registration`` fills it.
    phone: str = ""
    email: str
    insurer: str


class RegistrationResult(BaseModel):
    action: RegisterAction | None = None
    rejection: Rejection | None = None


# ---- diary/ ----------------------------------------------------------------

PartOfDay = Literal["morning", "afternoon"]


class ResolveDateInput(BaseModel):
    phrase: str = Field(description='As said: "next Thursday", "in a fortnight" ...')
    part_of_day: PartOfDay | None = None


class ResolvedWindow(BaseModel):
    date_from: date
    date_to: date
    time_from: time | None = None  # None = any time in the day
    time_to: time | None = None
    # True when the caller's day is closed and we moved to the next open day.
    moved_from_closed_day: bool = False
    rejection: Rejection | None = None


class FindSlotsInput(BaseModel):
    patient_id: str | None = None
    specialty_id: str | None = None
    provider_id: str | None = None
    location_id: str | None = None
    date_from: date
    date_to: date
    time_from: time | None = None
    time_to: time | None = None
    insurer: str | None = Field(default=None, description="Plan to price against")
    language: str | None = Field(default=None, description="ISO-639-1 the provider must speak")
    widen_days: int | None = Field(
        default=None,
        ge=1,
        le=45,
        description=(
            "Problem 7 (no slot free): when the exact window comes back genuinely "
            "empty (no_availability, never a closure or a rule), search this many "
            "days past date_to for the nearest alternative before giving up."
        ),
    )


class AvailabilityResult(BaseModel):
    slots: list[Slot] = Field(default_factory=list)
    blocked: list[BlockedProvider] = Field(default_factory=list)
    appointment_type: AppointmentTypeRecord | None = None
    rejection: Rejection | None = None
    widened: bool = Field(
        default=False, description="True when widen_days triggered a further search."
    )


class ListAppointmentsInput(BaseModel):
    patient_id: str
    when: Literal["upcoming", "past", "all"] = "upcoming"


class AppointmentList(BaseModel):
    appointments: list[Appointment] = Field(default_factory=list)


class PrepareBookingInput(BaseModel):
    patient_id: str
    slot: Slot
    policy_id: str


class BookingResult(BaseModel):
    action: BookAction | None = None
    rejection: Rejection | None = None


class PrepareRescheduleInput(BaseModel):
    appointment_id: str
    slot: Slot
    policy_id: str


class RescheduleResult(BaseModel):
    action: RescheduleAction | None = None
    rejection: Rejection | None = None


class PrepareCancelInput(BaseModel):
    appointment_id: str
    patient_id: str


class CancelResult(BaseModel):
    action: CancelAction | None = None
    rejection: Rejection | None = None


# ---- rules/ ----------------------------------------------------------------


class CheckEligibilityInput(BaseModel):
    patient_id: str
    specialty_id: str
    provider_id: str | None = None
    location_id: str | None = None
    insurer: str | None = None


class EligibilityVerdict(BaseModel):
    allowed: bool
    rejection: Rejection | None = None
    # Providers that can serve the same request when the named one cannot.
    redirect_to: list[ProviderRecord] = Field(default_factory=list)
    # What the verdict could not be sure of. Set when the directory record was
    # not in hand, so the rules read off it (age, referral, allowance) stood
    # down and only /availability answered. Never a refusal on its own.
    note: str = ""


class TriageInput(BaseModel):
    complaint: str = Field(
        description=(
            "Why they are calling, in the caller's own words, verbatim and never "
            "a summary: the symptom and any specialty they named. Dropping "
            "'gynaecology' from 'a gynaecology appointment for contraception "
            "questions' routes them to a GP."
        )
    )
    provider_name: str | None = Field(
        default=None,
        description="The doctor the caller named, as said. Their specialty is the one to book.",
    )


class TriageResult(BaseModel):
    specialty_id: str | None = None
    emergency: bool = False
    rejection: Rejection | None = None  # medical_emergency when emergency
    #: Set when a named doctor decided the specialty — the id to pass onward.
    provider_id: str | None = None


class NearestLocationInput(BaseModel):
    address: str = Field(description="Street address as said")
    specialty_id: str


class NearestLocationResult(BaseModel):
    location_id: str | None = None
    distance_km: float | None = None
    rejection: Rejection | None = None


class FindProviderInput(BaseModel):
    spoken_name: str
    specialty_id: str | None = None


class ProviderMatch(BaseModel):
    status: Literal["found", "ambiguous", "not_found", "on_leave"]
    provider: ProviderRecord | None = None
    candidates: list[ProviderRecord] = Field(default_factory=list)
    rejection: Rejection | None = None


#: A weekday as the caller says it. The tool input takes the name rather than
#: ``OpeningHours.weekday``'s number so a small model never has to count.
Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

WEEKDAY_IDS: tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


class ClinicFactsInput(BaseModel):
    """A question about the clinic itself (problem 16), answered off the catalogue.

    Fill only what the caller asked about; every filter narrows the sites.
    Empty = every site. The caller acts on the answer, so it comes from
    ``GET /clinic`` and never from memory.
    """

    location_id: str | None = Field(default=None, description="One site, when they named it")
    town: str | None = Field(default=None, description='A town or district as said: "Getafe"')
    specialty_id: str | None = Field(default=None, description="Keep sites with somebody in it")
    weekday: Weekday | None = Field(default=None, description="Keep sites that open that day")


class ProviderFact(BaseModel):
    provider_id: str
    name: str  # as spoken, title included
    specialty_id: str
    location_ids: list[str] = Field(default_factory=list)
    on_leave_until: date | None = None  # set when the leave covers the day of the call


class SiteFact(BaseModel):
    location_id: str
    name: str
    address: str = ""
    open_days: list[Weekday] = Field(default_factory=list)
    hours: list[OpeningHours] = Field(default_factory=list)
    #: Who sits here - narrowed to the specialty when one was asked about.
    providers: list[ProviderFact] = Field(default_factory=list)


class ClinicFacts(BaseModel):
    """What the catalogue says. An empty ``sites`` is an answer, not a failure."""

    sites: list[SiteFact] = Field(default_factory=list)
    closure_days: list[date] = Field(default_factory=list)  # network-wide, every site shut
    #: Set when the day or the specialty asked for leaves no site at all, so
    #: the call has the reason to submit if the caller still wants that.
    rejection: Rejection | None = None


# ---- line/ -----------------------------------------------------------------


class SubmitInput(BaseModel):
    action: Action


class SubmitResult(BaseModel):
    status: Literal["accepted", "duplicate", "late", "rejected", "unknown_call", "dry_run", "error"]
    http_status: int | None = None
    detail: str = ""


# ---------------------------------------------------------------------------
# 6. Frozen signatures
# ---------------------------------------------------------------------------


class FindPatientTool(Protocol):
    async def __call__(self, ctx: ToolContext, args: FindPatientInput) -> FindPatientResult: ...


class ValidateNationalIdTool(Protocol):
    async def __call__(
        self, ctx: ToolContext, args: ValidateNationalIdInput
    ) -> NationalIdCheck: ...


class BuildRegistrationTool(Protocol):
    async def __call__(
        self, ctx: ToolContext, args: BuildRegistrationInput
    ) -> RegistrationResult: ...


class ResolveDateTool(Protocol):
    async def __call__(self, ctx: ToolContext, args: ResolveDateInput) -> ResolvedWindow: ...


class FindSlotsTool(Protocol):
    async def __call__(self, ctx: ToolContext, args: FindSlotsInput) -> AvailabilityResult: ...


class ListAppointmentsTool(Protocol):
    async def __call__(self, ctx: ToolContext, args: ListAppointmentsInput) -> AppointmentList: ...


class PrepareBookingTool(Protocol):
    async def __call__(self, ctx: ToolContext, args: PrepareBookingInput) -> BookingResult: ...


class PrepareRescheduleTool(Protocol):
    async def __call__(
        self, ctx: ToolContext, args: PrepareRescheduleInput
    ) -> RescheduleResult: ...


class PrepareCancelTool(Protocol):
    async def __call__(self, ctx: ToolContext, args: PrepareCancelInput) -> CancelResult: ...


class CheckEligibilityTool(Protocol):
    async def __call__(
        self, ctx: ToolContext, args: CheckEligibilityInput
    ) -> EligibilityVerdict: ...


class TriageTool(Protocol):
    async def __call__(self, ctx: ToolContext, args: TriageInput) -> TriageResult: ...


class NearestLocationTool(Protocol):
    async def __call__(
        self, ctx: ToolContext, args: NearestLocationInput
    ) -> NearestLocationResult: ...


class FindProviderTool(Protocol):
    async def __call__(self, ctx: ToolContext, args: FindProviderInput) -> ProviderMatch: ...


class ClinicFactsTool(Protocol):
    async def __call__(self, ctx: ToolContext, args: ClinicFactsInput) -> ClinicFacts: ...


class SubmitTool(Protocol):
    async def __call__(self, ctx: ToolContext, args: SubmitInput) -> SubmitResult: ...


# ---------------------------------------------------------------------------
# 7. Stubs. Fake but well-formed. Ids here are invented; do not reuse them
#    as if they were the clinic's. The fake clinic client shares them so a
#    whole call runs coherently offline.
# ---------------------------------------------------------------------------

FAKE_PATIENT = PatientRecord(
    patient_id="P00042",
    given_name="Marta",
    first_surname="Ruiz",
    second_surname="López",
    national_id="12345678Z",
    date_of_birth=date(1985, 3, 12),
    phone="+34612345678",
    email="marta.ruiz@example.com",
    insurer="sanitas",
    has_visited_before=True,
    note="Fake record. Seen twice, both times by Dra. Ortiz at Arenal Centro.",
    referrals=[],
)

FAKE_PROVIDER = ProviderRecord(
    provider_id="PR01",
    name="Dra. Ortiz",
    specialty_id="general_practice",
    languages=["es", "en"],
    appointment_type_ids=["first_visit", "review"],
    location_ids=["centro"],
    insurer_ids_accepted=["sanitas", "adeslas", "asisa", "dkv", "privado"],
)

FAKE_REVIEW_TYPE = AppointmentTypeRecord(
    appointment_type_id="review",
    name="Review",
    specialty_id=None,
    duration_minutes=15,
    for_new_patients=False,
    guidance="Any returning patient in a specialty without its own review type.",
)


def _next_weekday_at(now: datetime, hour: int, minute: int = 0) -> datetime:
    """Tomorrow or later, Monday to Friday, at the given wall-clock time in Madrid."""
    day = now.astimezone(MADRID).date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return datetime.combine(day, time(hour, minute), tzinfo=MADRID)


def fake_slot(now: datetime) -> Slot:
    return Slot(
        start=_next_weekday_at(now, 10, 15),
        provider_id=FAKE_PROVIDER.provider_id,
        location_id="centro",
        appointment_type_id=FAKE_REVIEW_TYPE.appointment_type_id,
    )


async def stub_find_patient(ctx: ToolContext, args: FindPatientInput) -> FindPatientResult:
    return FindPatientResult(status="found", patient=FAKE_PATIENT)


async def stub_validate_national_id(
    ctx: ToolContext, args: ValidateNationalIdInput
) -> NationalIdCheck:
    value = args.value.replace(" ", "").replace("-", "").upper()
    return NationalIdCheck(normalized=value, kind="dni", valid=True, expected_letter=value[-1:])


async def stub_build_registration(
    ctx: ToolContext, args: BuildRegistrationInput
) -> RegistrationResult:
    return RegistrationResult(action=RegisterAction(**args.model_dump()))


async def stub_resolve_date(ctx: ToolContext, args: ResolveDateInput) -> ResolvedWindow:
    day = ctx.now.astimezone(MADRID).date() + timedelta(days=1)
    window = ResolvedWindow(date_from=day, date_to=day)
    if args.part_of_day == "morning":
        window.time_from, window.time_to = time(0, 0), time(14, 0)
    elif args.part_of_day == "afternoon":
        window.time_from, window.time_to = time(14, 0), time(23, 59)
    return window


async def stub_find_slots(ctx: ToolContext, args: FindSlotsInput) -> AvailabilityResult:
    return AvailabilityResult(slots=[fake_slot(ctx.now)], appointment_type=FAKE_REVIEW_TYPE)


async def stub_list_appointments(ctx: ToolContext, args: ListAppointmentsInput) -> AppointmentList:
    if args.when == "past":
        return AppointmentList()
    return AppointmentList(
        appointments=[
            Appointment(
                appointment_id="A0001",
                patient_id=args.patient_id,
                provider_id=FAKE_PROVIDER.provider_id,
                location_id="centro",
                appointment_type_id="review",
                start=_next_weekday_at(ctx.now + timedelta(days=7), 9, 30),
            )
        ]
    )


async def stub_prepare_booking(ctx: ToolContext, args: PrepareBookingInput) -> BookingResult:
    return BookingResult(
        action=BookAction(
            patient_id=args.patient_id,
            provider_id=args.slot.provider_id,
            location_id=args.slot.location_id,
            appointment_type_id=args.slot.appointment_type_id,
            slot=args.slot.start,
            policy_id=args.policy_id,
        )
    )


async def stub_prepare_reschedule(
    ctx: ToolContext, args: PrepareRescheduleInput
) -> RescheduleResult:
    return RescheduleResult(
        action=RescheduleAction(
            appointment_id=args.appointment_id,
            provider_id=args.slot.provider_id,
            location_id=args.slot.location_id,
            slot=args.slot.start,
            policy_id=args.policy_id,
        )
    )


async def stub_prepare_cancel(ctx: ToolContext, args: PrepareCancelInput) -> CancelResult:
    return CancelResult(action=CancelAction(appointment_id=args.appointment_id))


async def stub_check_eligibility(
    ctx: ToolContext, args: CheckEligibilityInput
) -> EligibilityVerdict:
    return EligibilityVerdict(allowed=True)


async def stub_triage(ctx: ToolContext, args: TriageInput) -> TriageResult:
    return TriageResult(specialty_id="general_practice", emergency=False)


async def stub_nearest_location(
    ctx: ToolContext, args: NearestLocationInput
) -> NearestLocationResult:
    return NearestLocationResult(location_id="centro", distance_km=1.2)


async def stub_find_provider(ctx: ToolContext, args: FindProviderInput) -> ProviderMatch:
    return ProviderMatch(status="found", provider=FAKE_PROVIDER)


async def stub_clinic_facts(ctx: ToolContext, args: ClinicFactsInput) -> ClinicFacts:
    return ClinicFacts(
        sites=[
            SiteFact(
                location_id="centro",
                name="Arenal Centro",
                open_days=["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"],
                providers=[
                    ProviderFact(
                        provider_id=FAKE_PROVIDER.provider_id,
                        name=FAKE_PROVIDER.name,
                        specialty_id=FAKE_PROVIDER.specialty_id,
                        location_ids=list(FAKE_PROVIDER.location_ids),
                    )
                ],
            )
        ]
    )


async def stub_submit(ctx: ToolContext, args: SubmitInput) -> SubmitResult:
    return SubmitResult(status="dry_run", detail="stub: nothing was sent")
