"""One ``CallSession`` per WebSocket. Nothing in here is shared between calls.

The session owns:
- the ``ToolContext`` every tool receives (call_id, clock, clinic, log, submitter)
- the call's ``CallMemory``: the last rejection a tool returned and the last
  action a tool prepared but nobody sent
- the caller's agreement to that action (``confirm_prepared``), and the
  submission it fires so the model never has to ask a second time
- the submit client and the record of what was submitted
- the end-of-call bookkeeping: summary line, fallback submission, cleanup

Lifecycle: ``CallSession.open(...)`` after the ``start`` message, ``close()``
once the socket is gone. ``close()`` runs the 30-second-window logic.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ValidationError

from vortex import tools as registry
from vortex.clinic import make_clinic_client
from vortex.clinic.client import ClinicApi
from vortex.contract import (
    INSURERS,
    MADRID,
    Action,
    Appointment,
    AppointmentList,
    BookAction,
    CallerLineMatch,
    CancelAction,
    DeclineReason,
    EligibilityVerdict,
    EscalateAction,
    FindPatientResult,
    FindSlotsInput,
    NoAction,
    PatientRecord,
    Rejection,
    RescheduleAction,
    Slot,
    SubmitInput,
    SubmitResult,
    ToolContext,
    action_route,
)
from vortex.conversation.language import DEFAULT_LANGUAGE, normalise_language
from vortex.diary.tools import _is_dead, find_slots
from vortex.identity.tools import PATIENT_PREFERENCES_KEY, resolve_caller_line
from vortex.line.confirmation_calls import (
    cancel_confirmation_calls,
    confirmation_store_from_settings,
    handoff_from_parameters,
    queue_cancellation_rebooking_call,
    schedule_confirmation_call,
)
from vortex.line.sms import (
    SMS_BUDGET_SECS,
    SMS_DETAILS_BUDGET_SECS,
    SmsClient,
    action_fingerprint,
    make_sms_client,
    notification_payload,
    render_confirmation_text,
    resolve_details,
)
from vortex.line.sms_reminders import (
    cancel_book_reminders,
    reminder_store_from_settings,
    schedule_book_reminder,
)
from vortex.line.submit import (
    DryRunSubmitClient,
    SubmitApi,
    SubmitClient,
    submit_action,
    submitted_action,
    with_verdict_reason,
)
from vortex.line.twilio import StartPayload
from vortex.line.usage import UsageTotals
from vortex.observability.calllog import CallLog
from vortex.observability.tracing import mask_phone, observe_span
from vortex.rules.triage import DEFAULT_SPECIALTY
from vortex.settings import Settings, get_settings

# The tool the model calls to send an action itself. It goes through
# ``ctx.submitter``, so the session has to be told about it by name.
SUBMIT_TOOL = "submit_action"

# The tools that draw an action up without sending it. Once the caller has
# agreed, what they prepare goes out in the same turn: see
# ``CallSession.confirm_prepared``.
PREPARE_TOOLS: tuple[str, ...] = ("prepare_booking", "prepare_reschedule", "prepare_cancel")

# What counts as an action the platform holds for this call. A 200 or a 409
# (the same action twice) is a record; everything else is not, ``dry_run``
# included - see ``CallSession.has_accepted_submission``.
ACCEPTED_STATUSES: tuple[str, ...] = ("accepted", "duplicate")

# SMS and the day-before confirmation call fire when we would have booked, not
# only when the platform holds the record. ``dry_run`` (no PLATFORM_API_KEY)
# still queues them so a local inbound demo can confirm the slot; hangup and
# ``has_accepted_submission`` stay on ``ACCEPTED_STATUSES`` alone.
QUEUE_FOLLOWUP_STATUSES: tuple[str, ...] = (*ACCEPTED_STATUSES, "dry_run")

# The tools that answer with the rule the clinic applied, named in the closed
# vocabulary the platform scores. Their reason is the call's verdict: a refusal
# has to carry it verbatim, whatever the model remembered. See
# ``CallMemory.last_verdict`` and the override in ``vortex/line/submit.py``.
VERDICT_TOOLS: frozenset[str] = frozenset({"check_eligibility", "find_slots"})

# The plan a booking is billed to when neither the patient's record nor the slot
# names one. The platform validates ``policy_id`` against ``INSURERS``, so a
# draft has to pick something the schema knows; self-pay is the one that claims
# no cover we have not seen.
SELF_PAY_POLICY = "privado"

# The refusal that wins nothing. ``out_of_scope`` claims the clinic line does not
# handle the request at all, and of the published cases not one is accepted on
# it: every ending is BOOK, REGISTER, or a refusal that names its rule. Where the
# fallback lands here it has named nothing, so the last-resort booking gets its
# try before this goes out. See ``CallSession.cold_booking``.
UNSCORED_REFUSAL = NoAction(reason="out_of_scope")

# How far ahead the last-resort booking looks for the first free slot. Two weeks
# is the longest span ``/availability`` answers in one request, and a slot past
# it is not what a caller who asked for nothing in particular wanted anyway.
COLD_BOOKING_HORIZON_DAYS = 14

# How long ``close`` will wait for in-flight SMS confirmations before giving up.
# Twilio is usually well under a second; this only bounds a hung send. It is the
# whole ``SMS_BUDGET_SECS``, the detail lookup included, because a shorter drain
# would cancel a POST that is still inside the client's own timeout and throw
# away a valid Twilio response.
SMS_DRAIN_TIMEOUT_SECS = SMS_BUDGET_SECS

# What a caller asks for when the conversation never resolves it. The last word
# wins: "move it — actually, cancel it" ends on cancel. Spanish and Catalan come
# through Soniox's transcript, which lower-cases, so case does not matter.
_CANCEL_INTENT = re.compile(r"\bcancel\w*\b|\banul\w*\b", re.IGNORECASE)
_MOVE_INTENT = re.compile(
    r"\b(?:move|moved|moving|reschedul\w*|rebook|postpon\w*|"
    r"put (?:it )?back|bring (?:it )?forward|push (?:it )?back|"
    r"mover|mueva|movedlo|moverla|moverlo|traslad\w*|aplaz\w*|pospon\w*|"
    r"adelant\w*|cambi\w*|canviar|canvi|endarrer\w*|avan\w*|"
    r"chang\w*)\b",
    re.IGNORECASE,
)
#: Words that take an intent back: "I don't want to cancel" is not a cancel ask.
#: A plain ``nt`` suffix is not here on purpose - "want" and "appointment" end
#: in it, and both are words a cancel or move ask uses.
_NEGATION = re.compile(
    r"\b(?:not|no|never|don't|dont|didn't|didnt|can't|cant|cannot|won't|wont|"
    r"sin|sense|ni|tampoco)\b",
    re.IGNORECASE,
)


def _last_intent(words: str) -> str | None:
    """``"cancel"`` or ``"move"``: the caller's last un-negated ask, if any.

    A clause is negated only inside its own segment - "no, that's not right,
    cancel it" still counts, because punctuation cuts the segment before the
    ask. The last surviving match wins, so a changed mind submits what the
    caller settled on.
    """
    best: tuple[int, str] | None = None
    for kind, pattern in (("cancel", _CANCEL_INTENT), ("move", _MOVE_INTENT)):
        for match in pattern.finditer(words):
            segment = re.split(r"[.!?;,\u2014\u2013]", words[: match.start()])[-1]
            if _NEGATION.search(segment):
                continue
            if best is None or match.start() > best[0]:
                best = (match.start(), kind)
    return best[1] if best else None


def refusal_for(reason: DeclineReason) -> Action:
    """The action a named reason ends on. A red flag goes to /escalate, the rest refuse."""
    if reason == "medical_emergency":
        return EscalateAction(reason=reason)
    return NoAction(reason=reason)


def policy_for(patient: PatientRecord, slot: Slot) -> str:
    """The plan to bill a drafted booking to: the record's, then the slot's, then self-pay."""
    candidates = (patient.insurer, *slot.payable_with, SELF_PAY_POLICY)
    policy = next(candidate for candidate in candidates if candidate in INSURERS)
    assert policy in INSURERS
    return policy


def booking_for(patient: PatientRecord, slot: Slot) -> BookAction:
    """One patient and one slot, as the action the platform scores.

    Every id but the plan comes straight off the slot the platform offered, the
    ``appointment_type_id`` included: the submitted type must be the slot's own,
    never one we decided.
    """
    assert patient.patient_id, "the directory never returns a match without an id"
    return BookAction(
        patient_id=patient.patient_id,
        provider_id=slot.provider_id,
        location_id=slot.location_id,
        appointment_type_id=slot.appointment_type_id,
        slot=slot.start,
        policy_id=policy_for(patient, slot),
    )


@dataclass
class CallMemory:
    """What the call learned, kept for the moment the line goes dead.

    Two things decide a silent call's last action: the last rule that bit (so
    the refusal can name it instead of ``out_of_scope``, which only ever matches
    problem 14) and the last action a tool prepared that nobody sent.

    One instance per ``ToolContext``, attached by ``CallSession.open`` and
    reachable with ``CallMemory.of(ctx)``. The conversation lane calls
    ``ctx.memory.mark_confirmed()`` the moment the caller says yes to what we
    read back; that is the only hook the prompt lane needs.

    The two memories exclude each other on purpose: a refusal after a prepared
    action drops the action (the rule bit after we drew it up), and a prepared
    action - or free slots coming back - drops the rejection (whatever blocked
    us no longer stands).
    """

    last_rejection: Rejection | None = None
    last_rejection_tool: str = ""
    # The subset of ``last_rejection`` the rules themselves answered: an
    # eligibility refusal or a provider ``find_slots`` reported as blocked. Both
    # are the reason a refusal must carry, so ``submit_action`` forces them; this
    # one goes first, because a later rejection is often its consequence.
    last_verdict: Rejection | None = None
    last_verdict_tool: str = ""
    # The same reason, kept across the action a tool later prepares around it.
    # A plan nobody confirmed must not cost the call a named reason: replacing
    # one with ``out_of_scope`` only ever loses the case. Free slots clear it,
    # because by then the rule no longer stands.
    stored_reason: Rejection | None = None
    stored_reason_tool: str = ""
    # The slot of the plan the last search superseded, for the log line only.
    superseded_slot: str = ""
    # A lookup ran and nobody was identified. The call ends on
    # ``patient_not_found``, which says what happened; ``out_of_scope`` claims
    # we could not serve the request at all, which is a different call.
    identity_pending: bool = False
    # The two halves of a booking the call had in hand: who is calling, and a
    # slot the platform offered. Kept apart from ``prepared`` because a call can
    # learn both and die before any tool draws the action up.
    identified_patient: PatientRecord | None = None
    # Who the dialling line belongs to, from the caller-id lookup at open. Kept
    # apart from ``identified_patient`` because it identifies the *line*: on a
    # third-party call the phone's owner is not the patient. A lookup the
    # conversation makes always wins; this is only what the call started with.
    caller_line: CallerLineMatch | None = None
    free_slot: Slot | None = None
    # What ``list_appointments`` read, for the caller-intent fallback: a caller
    # who asked to cancel or move a visit the conversation never resolved is
    # better served by acting on it than by a booking nobody asked for.
    diary: list[Appointment] = field(default_factory=list)
    prepared: Action | None = None
    prepared_tool: str = ""
    # Set by the conversation lane when the caller agrees to ``prepared``. It
    # survives a re-prepare of the same plan: the caller often says yes before
    # the model draws the action up again.
    confirmed: bool = False

    @classmethod
    def of(cls, ctx: ToolContext) -> CallMemory:
        """The context's memory, attached on first use. One per call, never shared."""
        memory = getattr(ctx, "memory", None)
        if not isinstance(memory, cls):
            memory = cls()
            ctx.memory = memory  # type: ignore[attr-defined]
        return memory

    def mark_confirmed(self) -> None:
        """The caller said yes to the prepared action. The prompt lane's hook."""
        self.confirmed = True

    def remember_rejection(self, tool: str, rejection: Rejection) -> None:
        self.last_rejection = rejection
        self.last_rejection_tool = tool
        if tool in VERDICT_TOOLS:
            self.last_verdict = rejection
            self.last_verdict_tool = tool
        self.stored_reason = rejection
        self.stored_reason_tool = tool
        self.prepared = None
        self.prepared_tool = ""
        self.confirmed = False

    def remember_prepared(self, tool: str, action: Action) -> None:
        if self.prepared is not None and self.prepared != action:
            self.confirmed = False
        self.prepared = action
        self.prepared_tool = tool
        self.forget_rejection()

    def forget_rejection(self) -> None:
        self.last_rejection = None
        self.last_rejection_tool = ""
        self.last_verdict = None
        self.last_verdict_tool = ""

    def forget_stored_reason(self) -> None:
        """Only for what proves the rule gone, never for a plan drawn up around it."""
        self.stored_reason = None
        self.stored_reason_tool = ""

    def forget_superseded_plan(self, slots: list[Slot]) -> str:
        """Drop a plan the caller has moved off. Returns its slot, or "".

        A fresh search whose slots do not hold the prepared one is the caller
        being offered something else: they asked for another site, another day,
        another doctor. The next "yes" belongs to that new offer, and spending it
        on the old plan books the slot they just turned down — and books it *as
        well as* the right one, because the model then draws the new plan up
        properly and sends that too. Two bookings is a mismatched record.

        ``confirmed`` is deliberately left alone. A caller who has already
        agreed to the new offer should not be asked twice: with nothing prepared,
        the next ``prepare_booking`` submits, which is what that flag is for.
        """
        slot = getattr(self.prepared, "slot", None)
        if not slot or any(free.start == slot for free in slots):
            return ""
        self.prepared = None
        self.prepared_tool = ""
        return slot

    @property
    def line_owner(self) -> PatientRecord | None:
        """The one patient the dialling line resolved to, if it resolved to one."""
        return self.caller_line.patient if self.caller_line is not None else None

    @property
    def patient_on_record(self) -> PatientRecord | None:
        """Who this call is for, on the best claim it has.

        Whoever the conversation identified, and failing that the owner of the
        dialling line. The line is the weaker claim - a third-party call books
        someone else - but it is the only one a call that never got a word in
        has, and every field on it came from ``/directory``.
        """
        return self.identified_patient or self.line_owner

    def draft_booking(self) -> BookAction | None:
        """The booking the call had every part of and nobody drew up.

        ``None`` unless the directory identified somebody and the platform
        offered a slot: a booking is only ours to draft off ids the API gave us.
        The slot is the most recent search's first, which is the one the caller
        was being read back when the line died.

        Who it is booked for is whoever the conversation identified; failing
        that, the owner of the dialling line, which the directory resolved from
        the caller id before the call began. The line owner is a weaker claim -
        a third-party call books someone else - but a slot was found for this
        call, so the alternative here is a refusal that scores nothing.
        """
        patient, slot = self.patient_on_record, self.free_slot
        if patient is None or slot is None or self.identity_pending:
            return None
        return booking_for(patient, slot)

    def observe(self, tool: str, result: Any) -> None:
        """Remember whatever a tool result says about where the call stands.

        Reads the contract's own field names, so no lane tool has to know this
        exists: ``rejection`` on every result that can refuse, ``action`` on the
        ``prepare_*`` and ``build_registration`` results, ``slots``/``blocked``
        on availability, ``status`` on the identity lookup, ``allowed`` on the
        eligibility verdict.
        """
        if isinstance(result, FindPatientResult):
            self.identity_pending = result.status != "found"
            if result.patient is not None and result.status == "found":
                self.identified_patient = result.patient

        if isinstance(result, AppointmentList):
            self.diary = result.appointments

        # A recheck the rules allow proves the earlier refusal gone, exactly as
        # free slots do. Left standing, its verdict would rewrite the reason of
        # every later refusal with a rule that no longer bites.
        if isinstance(result, EligibilityVerdict) and result.allowed:
            self.forget_rejection()
            self.forget_stored_reason()

        rejection = getattr(result, "rejection", None)
        if isinstance(rejection, Rejection):
            self.remember_rejection(tool, rejection)
        action = getattr(result, "action", None)
        if action is not None:
            self.remember_prepared(tool, action)

        slots = getattr(result, "slots", None)
        if slots is None:
            return
        # find_slots answers a blocked provider with the rule that blocked it
        # and no rejection - naming it as a refusal is the rules lane's call.
        # At the end of a dead call it is the only reason we have.
        blocked = getattr(result, "blocked", None) or []
        if slots:
            self.superseded_slot = self.forget_superseded_plan(slots)
            self.free_slot = slots[0]
            self.forget_rejection()
            self.forget_stored_reason()
        elif blocked and rejection is None:
            first = blocked[0]
            self.remember_rejection(
                tool, Rejection(reason=first.reason, detail=getattr(first, "detail", ""))
            )


@dataclass
class CallSession:
    settings: Settings
    start: StartPayload
    ctx: ToolContext
    submitter: SubmitApi
    media_frames_in: int = 0
    media_frames_out: int = 0
    # What this call spent at Soniox, the LLM host and Google TTS. Filled by
    # the pipecat observer from pipecat's own usage metrics; left at zero with
    # ``metered`` False by the lanes that do not measure. One per socket.
    usage: UsageTotals = field(default_factory=UsageTotals)
    submitted: list[SubmitResult] = field(default_factory=list)
    # Every action this call sent, in order, whatever the platform answered.
    # The fallback reads it to log whether a silent-call retry is a re-send.
    sent_actions: list[Action] = field(default_factory=list)
    end_reason: str = ""
    # Set the moment the platform accepts an action the model itself sent.
    # The pipeline reads it to hang up after the farewell instead of letting
    # the harness cut the call at three minutes. See ``arm_hangup``.
    hangup_reason: str = ""
    _closed: bool = False
    # Submissions fired by ``confirm_prepared``. Held so the loop cannot collect
    # one mid-flight, and so ``close`` waits for them before deciding a call
    # submitted nothing.
    _pending: set[asyncio.Task[Any]] = field(default_factory=set)
    # A refusal submission ``accept_refusal`` has already spawned. Nothing in
    # ``submit_accepted_refusal`` is true until its POST comes back, so two
    # acceptance frames in a row both pass its guards and both send the same
    # refusal. Reserved before the task starts, and never given back: a send
    # the platform did not take is the end-of-call fallback's to retry.
    _refusal_spawned: bool = False
    # SMS client for post-accept book/cancel texts. Built in ``open`` from
    # settings (Twilio when configured, dry-run otherwise). Tests swap it.
    sms: SmsClient = field(default_factory=lambda: make_sms_client(get_settings()))
    # In-flight SMS tasks. Drained in ``close`` so a hangup does not cancel them.
    _sms_pending: set[asyncio.Task[Any]] = field(default_factory=set)
    # Fingerprints of actions we already texted, so a 409 duplicate does not
    # SMS the caller twice for the same booking or cancel.
    _sms_notified: set[str] = field(default_factory=set)
    # The language this call is spoken in. The pipecat language watcher moves
    # it when the caller switches; the confirmation-call scheduling reads it so
    # tomorrow's outbound call speaks the language this caller actually used.
    language: str = DEFAULT_LANGUAGE
    # Set when the call arrives through an outbound-call handoff (a patient
    # who asked to move their appointment mid-confirmation-call): the
    # pipeline opens with the rebooking loop instead of the plain greeting.
    handoff: dict[str, str] | None = None

    @property
    def call_id(self) -> str:
        return self.ctx.call_id

    @property
    def stream_sid(self) -> str:
        return self.start.stream_sid

    @property
    def memory(self) -> CallMemory:
        """The call's memory. Lives on the ``ToolContext``, so tools share it."""
        return CallMemory.of(self.ctx)

    @classmethod
    def open(
        cls,
        start: StartPayload,
        *,
        settings: Settings | None = None,
        clinic: ClinicApi | None = None,
        now: datetime | None = None,
    ) -> CallSession:
        settings = settings or get_settings()
        log = CallLog(start.call_id)
        submitter: SubmitApi
        if settings.clinic_is_live:
            submitter = SubmitClient(settings.platform_api_base_url, settings.platform_api_key)
        else:
            submitter = DryRunSubmitClient()
        ctx = ToolContext(
            call_id=start.call_id,
            now=(now or datetime.now(MADRID)).astimezone(MADRID),
            from_number=start.from_number,
            clinic=clinic or make_clinic_client(settings),
            log=log,
            submitter=submitter,
        )
        ctx.settings = settings  # type: ignore[attr-defined]
        CallMemory.of(ctx)  # attach it before any tool runs
        session = cls(
            settings=settings,
            start=start,
            ctx=ctx,
            submitter=submitter,
            sms=make_sms_client(settings),
        )
        handoff = handoff_from_parameters(start.custom_parameters)
        if handoff is not None:
            session.handoff = handoff
            if handoff.get("language"):
                session.language = handoff["language"]
            # The booking this handoff call ends in (if any) replaces the
            # appointment that was cancelled to trigger it —
            # database/hooks.py's _record_booking reads this to link the two
            # rows in the product database.
            if handoff.get("appointment_id"):
                ctx.state["rebooking_from_appointment_id"] = handoff["appointment_id"]
            log.event(
                "call.handoff",
                appointment_id=handoff["appointment_id"],
                patient_id=handoff["patient_id"],
                language=handoff["language"],
            )
        log.event(
            "call.started",
            stream_sid=start.stream_sid,
            from_number=start.from_number,
            custom_parameters=start.custom_parameters,
            connected_at=ctx.now,
            **settings.describe(),
        )
        return session

    async def resolve_caller_line(self) -> CallerLineMatch:
        """Look the dialling line up before the caller speaks, and remember it.

        Called once by the voice pipeline while it is still being built, so the
        system prompt can name the caller instead of spending the first minute
        of a three-minute call asking who they are. Bounded by
        ``caller_id_lookup_timeout_secs``: the note is never worth holding the
        greeting for, and without it the call simply asks as it always did.
        """
        try:
            match = await asyncio.wait_for(
                resolve_caller_line(self.ctx),
                timeout=self.settings.caller_id_lookup_timeout_secs,
            )
        except TimeoutError:
            self.ctx.log.event("identity.caller_line_timed_out")
            match = CallerLineMatch()
        self.memory.caller_line = match
        return match

    async def call_tool(self, name: str, raw_args: dict[str, Any]) -> BaseModel:
        """Run one tool through the registry and keep what the end of the call needs.

        The registry validates, runs and logs; the session remembers. Two things
        are recorded here and nowhere else:

        - what the result says about where the call stands (``CallMemory``);
        - the model's own ``submit_action`` calls. Those reach the platform
          through ``ctx.submitter`` without passing ``CallSession.submit``, so
          without this the session would end a booked call believing it had
          submitted nothing and send a refusal on top of the booking.

        An accepted submission also arms the hangup: the call has nothing left
        to do, so the pipeline ends it after the farewell.
        """
        result = await registry.call_tool(name, self.ctx, raw_args)
        if name == SUBMIT_TOOL and isinstance(result, SubmitResult):
            self.submitted.append(result)
            sent: Action | None = None
            try:
                sent = SubmitInput.model_validate(raw_args).action
            except ValidationError:  # pragma: no cover - the registry validated it already
                pass
            else:
                # What left the process, reason override included, so the
                # fallback can tell a re-send from a first try.
                self.sent_actions.append(with_verdict_reason(self.ctx, sent))
            if result.status in ACCEPTED_STATUSES:
                self.arm_hangup("submit_accepted")
            if result.status in QUEUE_FOLLOWUP_STATUSES and sent is not None:
                follow_up = submitted_action(self.ctx, sent)
                self._queue_sms(follow_up)
                self._queue_confirmation_call(follow_up)
        else:
            self.memory.observe(name, result)
            if self.memory.superseded_slot:
                self.ctx.log.event(
                    "plan.superseded",
                    tool=name,
                    slot=self.memory.superseded_slot,
                    confirmed=self.memory.confirmed,
                )
                self.memory.superseded_slot = ""
            await self._submit_after_prepare(name)
        return result

    def confirm_prepared(self, why: str) -> None:
        """The caller said yes to the plan we read back. Never ask a second time.

        Called by the conversation lane's ``ConfirmationPolicy`` the moment an
        affirmation lands on a read-back. It records the agreement for the
        end-of-call fallback and, when an action is already drawn up, sends it:
        asking the same question twice is what cost the scored run its wall
        clock, and nothing un-sends an action that is already submitted.

        Synchronous on purpose. It is called from the frame path, where awaiting
        an HTTP POST would hold the caller's own audio, so the submission goes
        out as a task and ``close`` waits for it.
        """
        memory = self.memory
        if memory.confirmed:
            return
        memory.mark_confirmed()
        self.ctx.log.event(
            "confirm.affirmed",
            why=why,
            prepared_by=memory.prepared_tool,
            has_prepared=memory.prepared is not None,
        )
        if memory.prepared is not None:
            self._spawn(self.submit_confirmed_prepared("affirmation"))

    def accept_refusal(self, why: str) -> None:
        """The caller accepted a rule that already bit. Do not ask again.

        Call ``6d537b3a``: eligibility refused, they said "Ah, I see", and the
        model asked about another policy until they hung up. The refusal was
        already the ending. A booking still on the table is not this path.
        """
        memory = self.memory
        if self.has_accepted_submission or self._refusal_spawned:
            return
        if memory.prepared is not None or memory.last_rejection is None:
            return
        self.ctx.log.event(
            "refusal.accepted",
            why=why,
            reason=memory.last_rejection.reason,
            tool=memory.last_rejection_tool,
        )
        self._refusal_spawned = True
        self._spawn(self.submit_accepted_refusal())

    async def submit_accepted_refusal(self) -> SubmitResult | None:
        """Send the stored refusal once, the moment the caller accepted it.

        A refusal the caller has accepted is the whole ending of the call: there
        is no second action to draw up and no question left to ask. So unlike
        ``submit_confirmed_prepared`` this arms the hangup as soon as the
        platform holds it, and the pipeline ends after the goodbye instead of
        running to the three-minute cap.
        """
        memory = self.memory
        if self.has_accepted_submission or memory.last_rejection is None:
            return None
        if memory.prepared is not None:
            return None
        action = with_verdict_reason(self.ctx, refusal_for(memory.last_rejection.reason))
        if action in self.sent_actions:
            return None
        self.ctx.log.event(
            "submit.on_refusal_accepted",
            reason=memory.last_rejection.reason,
            route=action_route(action),
        )
        result = await self.submit(action)
        if result.status in ACCEPTED_STATUSES:
            self.arm_hangup("submit_accepted")
        return result

    async def submit_confirmed_prepared(self, trigger: str) -> SubmitResult | None:
        """Send the prepared action the caller has agreed to, once.

        ``None`` when there is nothing to send: no action drawn up, no agreement
        yet, or this exact action already left.

        This does not arm the hangup. The call may still have a second thing to
        do (a cancel and a booking are two actions), and the caller has not been
        said goodbye to yet; the model's own ``submit_action`` - a duplicate of
        this one, which the platform answers 409 - is what ends the call, as it
        did before.
        """
        memory = self.memory
        action = memory.prepared
        if action is None or not memory.confirmed or action in self.sent_actions:
            return None
        self.ctx.log.event(
            "submit.on_confirmation",
            trigger=trigger,
            route=action_route(action),
            prepared_by=memory.prepared_tool,
        )
        return await self.submit(action)

    async def _submit_after_prepare(self, tool: str) -> None:
        """A ``prepare_*`` after the caller's yes needs no second question."""
        if tool in PREPARE_TOOLS:
            await self.submit_confirmed_prepared(tool)

    def _spawn(self, coro: Any) -> None:
        """Run a submission off the frame path, and keep hold of it."""
        try:
            task = asyncio.get_running_loop().create_task(coro)
        except RuntimeError:  # no loop: nothing can be sent from here
            coro.close()
            return
        self._pending.add(task)
        task.add_done_callback(self._pending_done)

    def _pending_done(self, task: asyncio.Task[Any]) -> None:
        self._pending.discard(task)
        if not task.cancelled() and task.exception() is not None:
            self.ctx.log.event("submit.on_confirmation_failed", error=repr(task.exception()))

    def arm_hangup(self, reason: str) -> None:
        """The call is done: let the pipeline end it once the agent stops talking.

        Only an action the platform *holds* arms this. A rejection, a late
        submission or a dry run leaves the call running, because the model may
        still fix what it sent and the end-of-call fallback is still the last
        word. Armed once, it stays armed: the first reason is the true one.
        """
        if not self.hangup_reason:
            self.hangup_reason = reason

    @property
    def hangup_armed(self) -> bool:
        """Has the call earned the right to hang up from our side?"""
        return bool(self.hangup_reason)

    async def submit(self, action: Action) -> SubmitResult:
        result = await submit_action(self.ctx, SubmitInput(action=action))
        self.submitted.append(result)
        self.sent_actions.append(with_verdict_reason(self.ctx, action))
        if result.status in QUEUE_FOLLOWUP_STATUSES:
            follow_up = submitted_action(self.ctx, action)
            self._queue_sms(follow_up)
            self._queue_confirmation_call(follow_up)
        return result

    @property
    def has_accepted_submission(self) -> bool:
        """Does the platform hold an action for this call?

        ``dry_run`` is not acceptance: with no ``PLATFORM_API_KEY`` nothing
        leaves the process, so a dry run is a line in the log, not a record on
        the platform. Leaving it out is what keeps the fallback exercised - and
        logged - in fake mode, which is the only mode the tests and the offline
        rehearsals run in. ``late``, ``rejected``, ``unknown_call`` and
        ``error`` are not acceptance either: the platform has nothing, so the
        fallback still gets its try inside the window.
        """
        return any(r.status in ACCEPTED_STATUSES for r in self.submitted)

    async def close(self, reason: str = "socket_closed", **extra: Any) -> None:
        """End-of-call bookkeeping. Safe to call twice."""
        if self._closed:
            return
        self._closed = True
        self.end_reason = reason
        # Before ``call.ended``, and on every close reason including a crash:
        # the dashboard prices a call in euros and an unpriced call is a hole
        # in the total. A lane that does not measure still writes the line,
        # with ``metered`` false, so "no cost" never reads as "no data".
        self.ctx.log.event("call.usage", **self.usage.payload(self.settings))
        self.ctx.log.event(
            "call.ended",
            reason=reason,
            media_frames_in=self.media_frames_in,
            media_frames_out=self.media_frames_out,
            **extra,
        )
        try:
            await asyncio.wait_for(
                self._fallback_if_silent(),
                timeout=self.settings.submit_window_secs
                - self.settings.submit_deadline_margin_secs,
            )
        except TimeoutError:
            self.ctx.log.event("submit.fallback_timed_out")
        finally:
            await self._drain_sms()
            self.ctx.log.summary(reason=reason, usage=self.usage.summary_extras())
            # Land the whole call in Postgres before the process forgets it.
            # In a worker thread: the same loop is streaming audio for up to
            # nineteen other sockets, and this blocks on HTTP.
            await asyncio.to_thread(self.ctx.log.flush)
            await self.sms.aclose()
            await self.submitter.aclose()

    def _queue_confirmation_call(self, action: Action) -> None:
        """Queue the day-before confirmation call (book) or the immediate
        call_now rebooking call (cancel) off the submit path.

        Same discipline as ``_queue_sms``: never blocks the call, never raises
        into it, and a 409 duplicate does not schedule twice (the store dedupes
        a pending row for the same number and slot).
        """
        if not isinstance(action, (BookAction, CancelAction)):
            return
        if not self.settings.confirmation_calls:
            self.ctx.log.event(
                "confirmation_call.skipped", reason="disabled", action_kind=action.kind
            )
            return
        try:
            task = asyncio.get_running_loop().create_task(self._sync_confirmation_call(action))
        except RuntimeError:
            return
        self._sms_pending.add(task)
        task.add_done_callback(self._sms_pending_done)

    async def _sync_confirmation_call(self, action: Action) -> None:
        """Schedule the day-before confirmation call (book), or drop it and
        queue an immediate call_now rebooking call instead (cancel). Never
        raises."""
        try:
            forced = bool(self.settings.confirmation_force_to or self.settings.sms_force_to)
            to = (
                self.settings.confirmation_force_to
                or self.settings.sms_force_to
                or self.ctx.from_number
                or ""
            ).strip()
            if not to:
                self.ctx.log.event(
                    "confirmation_call.skipped", reason="no_from_number", action_kind=action.kind
                )
                return
            store = confirmation_store_from_settings(self.settings)
            lead = timedelta(hours=float(self.settings.confirmation_lead_hours))
            if isinstance(action, BookAction):
                details = await resolve_details(self.ctx, action)
                when = details.when
                if when is None:
                    self.ctx.log.event("confirmation_call.skipped", reason="no_when")
                    return
                call = await schedule_confirmation_call(
                    store,
                    to=to,
                    when=when,
                    language=normalise_language(self.language) or "",
                    provider_name=details.provider_name,
                    location_name=details.location_name,
                    provider_id=details.provider_id,
                    location_id=details.location_id,
                    patient_id=action.patient_id,
                    appointment_id=await self._booked_appointment_id(action),
                    now=self.ctx.now,
                    lead=lead,
                )
                if call is None:
                    self.ctx.log.event("confirmation_call.skipped", reason="within_lead_window")
                    return
                self.ctx.log.event(
                    "confirmation_call.scheduled",
                    call_at=call.call_at,
                    appointment_at=call.appointment_at,
                    language=call.language,
                    to=mask_phone(to),
                    forced=forced,
                )
                return
            if isinstance(action, CancelAction):
                details = await resolve_details(self.ctx, action)
                count = await cancel_confirmation_calls(
                    store,
                    to=to,
                    appointment_at=details.when,
                    appointment_id=action.appointment_id,
                )
                self.ctx.log.event(
                    "confirmation_call.cancelled",
                    count=count,
                    appointment_id=action.appointment_id,
                )
                if self.handoff is not None:
                    # This call started life as a confirmation call's own
                    # reschedule offer (CallSession.handoff): the patient
                    # was just asked "¿otra fecha?" live, on this very call.
                    # Queuing another call_now on top would re-dial someone
                    # who is (or just was) on the phone with us.
                    self.ctx.log.event(
                        "confirmation_call.rebooking_skipped", reason="already_offered_on_call"
                    )
                    return
                if details.when is None:
                    self.ctx.log.event("confirmation_call.rebooking_skipped", reason="no_when")
                    return
                patient = self.memory.patient_on_record
                rebooking_call = await queue_cancellation_rebooking_call(
                    self.settings,
                    to=to,
                    appointment_at=details.when,
                    language=normalise_language(self.language) or "",
                    provider_name=details.provider_name,
                    location_name=details.location_name,
                    provider_id=details.provider_id,
                    location_id=details.location_id,
                    patient_id=patient.patient_id if patient is not None else "",
                    appointment_id=action.appointment_id,
                    now=self.ctx.now,
                )
                if rebooking_call is None:
                    self.ctx.log.event(
                        "confirmation_call.rebooking_skipped", reason="disabled_or_no_to"
                    )
                    return
                self.ctx.log.event(
                    "confirmation_call.rebooking_queued",
                    call_at=rebooking_call.call_at,
                    appointment_at=rebooking_call.appointment_at,
                    to=mask_phone(to),
                )
        except Exception as exc:  # noqa: BLE001 - never break the call for this
            self.ctx.log.event("confirmation_call.failed", error=repr(exc))

    def _queue_sms(self, action: Action) -> None:
        """Fire a confirmation SMS off the submit path. Never blocks the call."""
        if not isinstance(action, (BookAction, CancelAction)):
            return
        if not self.settings.sms_confirmations:
            self.ctx.log.event("sms.skipped", reason="disabled", action_kind=action.kind)
            return
        fingerprint = action_fingerprint(action)
        if fingerprint in self._sms_notified:
            self.ctx.log.event("sms.skipped", reason="already_notified", action_kind=action.kind)
            return
        self._sms_notified.add(fingerprint)
        try:
            task = asyncio.get_running_loop().create_task(self._send_sms(action))
        except RuntimeError:
            self._sms_notified.discard(fingerprint)
            return
        self._sms_pending.add(task)
        task.add_done_callback(self._sms_pending_done)

    def _sms_pending_done(self, task: asyncio.Task[Any]) -> None:
        self._sms_pending.discard(task)
        if not task.cancelled() and task.exception() is not None:
            self.ctx.log.event("sms.failed", error=repr(task.exception()))

    async def _send_sms(self, action: Action) -> None:
        forced = bool(self.settings.sms_force_to)
        to = (self.settings.sms_force_to or self.ctx.from_number or "").strip()
        if not to:
            self.ctx.log.event("sms.skipped", reason="no_from_number", action_kind=action.kind)
            return
        details = await resolve_details(self.ctx, action)
        body = render_confirmation_text(action, details)
        payload = notification_payload(action, details)
        self.ctx.log.event(
            "sms.sending",
            to=mask_phone(to),
            forced=forced,
            **payload,
        )
        result = await self.sms.send(to=to, body=body)
        self.ctx.log.event(
            f"sms.{result.status}",
            to=mask_phone(result.to or to),
            detail=result.detail,
            sid=result.sid,
            forced=forced,
            **payload,
        )
        if self.settings.sms_day_before_reminders:
            await self._sync_reminders(action, to=to, details=details)

    async def _booked_appointment_id(self, action: BookAction) -> str:
        """The platform id of the visit a ``BookAction`` just created.

        Best effort with the SMS details budget: the confirmation call still
        schedules without it, but a handed-off reschedule needs the real id -
        ``prepare_reschedule`` rejects anything the clinic API never issued.
        """
        try:
            items = await asyncio.wait_for(
                self.ctx.clinic.appointments(action.patient_id), SMS_DETAILS_BUDGET_SECS
            )
        except Exception as exc:  # noqa: BLE001 - never breaks the call
            self.ctx.log.event(
                "confirmation_call.appointment_lookup_failed", error=type(exc).__name__
            )
            return ""
        for item in items:
            if (
                item.provider_id == action.provider_id
                and item.location_id == action.location_id
                and item.start == action.slot
            ):
                return item.appointment_id
        return ""

    async def _sync_reminders(self, action: Action, *, to: str, details: object) -> None:
        """Queue or drop the day-before reminder. Never raises into the call."""
        try:
            store = reminder_store_from_settings(self.settings)
            lead = timedelta(hours=float(self.settings.sms_reminder_lead_hours))
            if isinstance(action, BookAction):
                when = getattr(details, "when", None)
                if when is None:
                    self.ctx.log.event(
                        "sms.reminder_skipped",
                        reason="no_when",
                        action_kind=action.kind,
                    )
                    return
                reminder = await schedule_book_reminder(
                    store,
                    to=to,
                    when=when,
                    provider_name=getattr(details, "provider_name", "") or "",
                    location_name=getattr(details, "location_name", "") or "",
                    provider_id=getattr(details, "provider_id", "") or "",
                    location_id=getattr(details, "location_id", "") or "",
                    patient_id=getattr(action, "patient_id", "") or "",
                    now=self.ctx.now,
                    lead=lead,
                )
                if reminder is None:
                    self.ctx.log.event(
                        "sms.reminder_skipped",
                        reason="within_lead_window",
                        action_kind=action.kind,
                    )
                    return
                self.ctx.log.event(
                    "sms.reminder_scheduled",
                    send_at=reminder.send_at,
                    appointment_at=reminder.appointment_at,
                    to=mask_phone(to),
                )
                return
            if isinstance(action, CancelAction):
                count = await cancel_book_reminders(
                    store,
                    to=to,
                    appointment_at=getattr(details, "when", None),
                    appointment_id=action.appointment_id,
                )
                self.ctx.log.event(
                    "sms.reminder_cancelled",
                    count=count,
                    appointment_id=action.appointment_id,
                )
        except Exception as exc:  # noqa: BLE001 - reminders must not break the call
            self.ctx.log.event("sms.reminder_failed", error=repr(exc))

    async def _drain_sms(self) -> None:
        if not self._sms_pending:
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*tuple(self._sms_pending), return_exceptions=True),
                timeout=SMS_DRAIN_TIMEOUT_SECS,
            )
        except TimeoutError:
            self.ctx.log.event("sms.drain_timed_out", pending=len(self._sms_pending))

    async def _fallback_if_silent(self) -> None:
        """Submitting nothing always fails. A typed refusal never scores worse.

        Scoring is binary per case, so a wrong action costs exactly what silence
        costs and a right one wins the case. The branches below are ordered by
        how likely each is to be the answer the case expects.

        A submission fired by ``confirm_prepared`` may still be in flight when
        the socket dies, so it is waited for first: otherwise this would send a
        refusal on top of the booking the caller agreed to.
        """
        if self._pending:
            await asyncio.gather(*tuple(self._pending), return_exceptions=True)
        if self.has_accepted_submission:
            return
        branch, action, why = self.fallback_action()
        if action == UNSCORED_REFUSAL:
            intent_action = await self._caller_intent_action()
            if intent_action is not None:
                branch = "caller_intent"
                why = f"{why}; the caller's own words asked to change or cancel a known visit"
                action = intent_action
            else:
                booking = await self.cold_booking()
                if booking is not None:
                    branch = "cold_booking"
                    why = f"{why}, and out_of_scope wins no case: booked what the line points at"
                    action = booking
        with observe_span(
            "submit-fallback",
            input={"branch": branch, "why": why, "route": action_route(action)},
        ) as span:
            await self._send_fallback(branch, action, why, span)

    async def _send_fallback(self, branch: str, action: Action, why: str, span: Any = None) -> None:
        # An earlier send of this action may have returned error / dry_run /
        # rejected: the platform holds nothing. Retry so an ambiguous first
        # request can still land as accepted or duplicate (409).
        retrying = action in self.sent_actions
        self.ctx.log.event(
            "submit.fallback",
            branch=branch,
            why=why,
            route=action_route(action),
            skipped=False,
            retrying=retrying,
            sent_so_far=len(self.submitted),
        )
        if span is not None:
            span.update(output={"skipped": False, "retrying": retrying, "branch": branch})
        await self.submit(action)

    async def cold_booking(self) -> BookAction | None:
        """The booking the dialling line implies, for a call that resolved nothing.

        Reached only where the fallback has named nothing and would send
        ``out_of_scope``, which no published case accepts and which is therefore
        a certain zero. The call still knows who dialled: the caller-id lookup
        runs before the greeting, so a call the agent never got a word into ends
        holding a ``patient_id`` from ``/directory`` and the habits mined off
        that patient's visit history. This asks the platform for the slot those
        habits point at and books it.

        ``None`` whenever the guess would not be ours to make: nobody on the
        line, no slot free, or the platform did not answer in time. Every one of
        those leaves the refusal the fallback already chose in place - a booking
        nobody sends is worth less than a refusal that goes out inside the
        window.
        """
        patient = self.memory.patient_on_record
        if patient is None:
            return None
        try:
            slot = await asyncio.wait_for(
                self._first_slot_for(patient),
                timeout=self.settings.cold_booking_timeout_secs,
            )
        except TimeoutError:
            self.ctx.log.event("submit.cold_booking_timed_out", patient_id=patient.patient_id)
            return None
        except Exception as exc:
            self.ctx.log.event("submit.cold_booking_failed", detail=f"{type(exc).__name__}: {exc}")
            return None
        if slot is None:
            return None
        booking = booking_for(patient, slot)
        self.ctx.log.event(
            "submit.cold_booking",
            patient_id=booking.patient_id,
            provider_id=booking.provider_id,
            location_id=booking.location_id,
            appointment_type_id=booking.appointment_type_id,
            slot=booking.slot,
            from_line=self.memory.identified_patient is None,
        )
        return booking

    async def _first_slot_for(self, patient: PatientRecord) -> Slot | None:
        """The first slot the platform offers this patient, their habits first.

        Two searches at most: the doctor and site every past visit of theirs
        used, then general practice anywhere. ``/availability`` answers no query
        that names neither a provider nor a specialty, so the open search still
        has to name one, and general practice is what a scheduling line is asked
        for when it was not asked for anything.

        Both go through the diary lane's ``find_slots``, so the same-day rule,
        the site calendar and the span the platform accepts stay in one place,
        and the slots come back priced against this patient's own plan.
        """
        today = self.ctx.now.astimezone(MADRID).date()
        window = {
            "patient_id": patient.patient_id,
            "date_from": today,
            "date_to": today + timedelta(days=COLD_BOOKING_HORIZON_DAYS),
        }
        queries = []
        provider, location = self._habits_of(patient)
        if provider:
            queries.append(FindSlotsInput(provider_id=provider, location_id=location, **window))
        queries.append(FindSlotsInput(specialty_id=DEFAULT_SPECIALTY, **window))
        for query in queries:
            result = await find_slots(self.ctx, query)
            if result.slots:
                return result.slots[0]
        return None

    async def _caller_intent_action(self) -> Action | None:
        """The cancel or reschedule the caller asked for and never got.

        Reached where the fallback would send ``out_of_scope`` - a certain
        zero, so a wrong guess here costs nothing the refusal was keeping. The
        record comes from ``list_appointments``, filtered to the caller's own
        visits that are still live, and it acts only on exactly one: with two
        or more the visit to act on is the caller's to say, and guessing there
        loses the same zero anyway.
        """
        patient = self.memory.patient_on_record
        if patient is None:
            return None
        live = [
            appointment
            for appointment in self.memory.diary
            if appointment.patient_id == patient.patient_id
            and appointment.start > self.ctx.now
            and not _is_dead(appointment)
        ]
        if len(live) != 1:
            return None
        intent = _last_intent(self.ctx.log.caller_words())
        if intent is None:
            return None
        appointment = live[0]
        if intent == "cancel":
            action: Action = CancelAction(appointment_id=appointment.appointment_id)
        else:
            action = await self._reschedule_guess(appointment)
            if action is None:
                return None
        self.ctx.log.event(
            "submit.caller_intent",
            intent=intent,
            appointment_id=appointment.appointment_id,
            route=action_route(action),
        )
        return action

    async def _reschedule_guess(self, appointment: Appointment) -> RescheduleAction | None:
        """First slot after theirs, same doctor and site - the move the case asks for.

        The search runs through the diary lane's ``find_slots`` so closures and
        the same-day rule stay in one place; the floor is the visit's own day
        because a later hour that same day is still "after it". No slot found
        is ``None``, not a different guess: the refusal already chosen stands.
        """
        day = appointment.start.astimezone(MADRID).date()
        patient = self.memory.patient_on_record
        assert patient is not None  # the caller checked before this was reached
        try:
            result = await asyncio.wait_for(
                find_slots(
                    self.ctx,
                    FindSlotsInput(
                        provider_id=appointment.provider_id,
                        location_id=appointment.location_id,
                        patient_id=patient.patient_id,
                        insurer=patient.insurer or None,
                        date_from=day,
                        date_to=day + timedelta(days=COLD_BOOKING_HORIZON_DAYS),
                    ),
                ),
                timeout=self.settings.cold_booking_timeout_secs,
            )
        except TimeoutError:
            self.ctx.log.event("submit.caller_intent_timed_out")
            return None
        except Exception as exc:
            self.ctx.log.event("submit.caller_intent_failed", detail=f"{type(exc).__name__}: {exc}")
            return None
        later = next((slot for slot in result.slots if slot.start > appointment.start), None)
        if later is None:
            return None
        return RescheduleAction(
            appointment_id=appointment.appointment_id,
            provider_id=later.provider_id,
            location_id=later.location_id,
            slot=later.start,
            policy_id=policy_for(patient, later),
        )

    def _habits_of(self, patient: PatientRecord) -> tuple[str | None, str | None]:
        """The doctor and site this patient has always used, or ``(None, None)``.

        Read from what the identity lane mined in the background when the caller
        id resolved, and only when it mined it for this patient: a call that
        identified somebody else later must not book against the line owner's
        habits. Unanimous or nothing - a patient who has seen two doctors has no
        habit worth guessing from.
        """
        habits = self.ctx.state.get(PATIENT_PREFERENCES_KEY) or {}
        if habits.get("patient_id") != patient.patient_id:
            return None, None
        return habits.get("provider_preference") or None, habits.get("location_preference") or None

    def fallback_action(self) -> tuple[str, Action, str]:
        """The action a silent call ends on: (branch, action, why)."""
        memory = self.memory

        # (a) Something was drawn up, agreed to, and never sent. The caller's
        #     yes outranks every reason below it, a named rule included.
        if memory.prepared is not None and memory.confirmed:
            return (
                "prepared",
                memory.prepared,
                f"{memory.prepared_tool} prepared an action nobody sent "
                f"(confirmed={memory.confirmed})",
            )

        # (b) The last rule that bit. This is the branch that earns points:
        #     out_of_scope matches problem 14 and nothing else, while a named
        #     reason matches the refusal endings of problems 6, 7, 10 and 16.
        #     A red flag is the one ending the platform expects on /escalate.
        #     The verb is the rejection's, the reason the rules' verdict where
        #     the call holds one: the same swap ``submit_action`` makes, done
        #     here so the branch we log is the action that goes out and the
        #     re-send check in ``_send_fallback`` compares like with like.
        if memory.last_rejection is not None:
            reason = memory.last_rejection.reason
            return (
                "last_rejection",
                with_verdict_reason(self.ctx, refusal_for(reason)),
                f"{memory.last_rejection_tool} refused: {reason}",
            )

        # (c) A rule bit earlier and a tool then drew up a plan around it that
        #     nobody confirmed. The rule is still the last thing we learned, so
        #     it names the ending: a stored reason is never worth trading for
        #     out_of_scope.
        if memory.stored_reason is not None:
            reason = memory.stored_reason.reason
            return (
                "stored_reason",
                refusal_for(reason),
                f"{memory.stored_reason_tool} refused: {reason}, before a plan nobody confirmed",
            )

        # (d) A plan the caller never got to agree to, with no rule against it.
        #     Scoring is binary per case, so an action the case does not accept
        #     costs exactly what a refusal it does not accept costs - and of the
        #     23 published cases every single one ends on BOOK, REGISTER or one
        #     of three named refusals, never on the out_of_scope this used to
        #     fall through to. A call that got as far as drawing an action up is
        #     a call whose ending we already know.
        if memory.prepared is not None:
            return (
                "prepared_unconfirmed",
                memory.prepared,
                f"{memory.prepared_tool} prepared an action nobody confirmed",
            )

        # (e) No plan, but the call holds both halves of one: the patient the
        #     directory identified and a slot the platform offered. Both ids
        #     come from the API, so the draft is exact where it is right.
        draft = memory.draft_booking()
        if draft is not None:
            return (
                "draft_booking",
                draft,
                "the call identified a patient and held a free slot, and drew nothing up",
            )

        # (f) Nobody said anything we could act on: a dropped or silent call.
        if self.ctx.log.user_turns == 0:
            return (
                "no_turns",
                NoAction(reason="out_of_scope"),
                "the caller never said anything we could act on",
            )

        # (g) The line died with the lookup still open: a patient was searched
        #     for and none was identified. That is patient_not_found, and it is
        #     the one thing out_of_scope certainly is not - the request was ours
        #     to serve, we just never learned whose it was.
        if memory.identity_pending:
            return (
                "identity_pending",
                NoAction(reason="patient_not_found"),
                "a lookup ran and identified nobody",
            )

        # (h) A real conversation that resolved nothing, and no rule to name.
        #     NO_ACTION, not ESCALATE. The problem set pairs ESCALATE with one
        #     ending only - a red flag, with medical_emergency - and branch (b)
        #     already covers it from triage's own rejection. An ESCALATE
        #     anywhere else is a verb no case accepts, so it can only lose a
        #     case that NO_ACTION might still win: out_of_scope is the expected
        #     ending of the adversarial cases and the right shape of answer
        #     wherever we simply could not tell what was being asked.
        return (
            "default",
            NoAction(reason="out_of_scope"),
            "the call ended with nothing resolved and no rule to name",
        )
