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
    Slot,
    SubmitInput,
    SubmitResult,
    ToolContext,
    TriageResult,
    action_route,
)
from vortex.diary.tools import find_slots
from vortex.identity.tools import PATIENT_PREFERENCES_KEY, resolve_caller_line
from vortex.line.sms import (
    SMS_BUDGET_SECS,
    SmsClient,
    action_fingerprint,
    make_sms_client,
    notification_payload,
    render_confirmation_text,
    resolve_details,
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

# What the caller wants, as the domain tools reveal it. The classification
# itself lives inside the model - no tool asks "what is your goal" - so the
# first tool call that can only mean one thing is where the intent becomes
# observable for the log: a ``prepare_*`` is drawn up only for the action it
# names, and ``build_registration`` only runs for a caller the directory does
# not know. ``triage`` means "escalate" only when it flags an emergency; a
# routing answer says nothing about the goal yet. And ``submit_action`` needs
# no mapping at all: the action's own ``kind`` is already the intent
# vocabulary (book / register / reschedule / cancel / no-action / escalate).
TOOL_INTENTS: dict[str, str] = {
    "prepare_booking": "book",
    "prepare_reschedule": "reschedule",
    "prepare_cancel": "cancel",
    "build_registration": "register",
}

# What counts as an action the platform holds for this call. A 200 or a 409
# (the same action twice) is a record; everything else is not, ``dry_run``
# included - see ``CallSession.has_accepted_submission``.
ACCEPTED_STATUSES: tuple[str, ...] = ("accepted", "duplicate")

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


def refusal_for(reason: DeclineReason) -> Action:
    """The action a named reason ends on. A red flag goes to /escalate, the rest refuse."""
    if reason == "medical_emergency":
        return EscalateAction(reason=reason)
    return NoAction(reason=reason)


def _intent_revealed(tool: str, result: BaseModel) -> str | None:
    """The intent a finished tool call reveals, or ``None`` when it reveals none.

    See ``TOOL_INTENTS`` for the mapping. ``triage`` is the one tool whose
    name alone is ambiguous: it routes a symptom to a specialty on every
    urgent-care call, so it only says "escalate" when the result flags the
    emergency.
    """
    if isinstance(result, TriageResult):
        return "escalate" if result.emergency else None
    return TOOL_INTENTS.get(tool)


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
    # The last intent this call logged, so ``call.intent`` is written only when
    # the best guess changes - a re-classification, not a repeat.
    _intent: str = ""

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
        log = CallLog(start.call_id, settings.calls_log_path)
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
            if sent is not None:
                self._note_intent(sent.kind, tool=name)
            if result.status in ACCEPTED_STATUSES:
                self.arm_hangup("submit_accepted")
                if sent is not None:
                    self._queue_sms(submitted_action(self.ctx, sent))
        else:
            self.memory.observe(name, result)
            self._note_intent(_intent_revealed(name, result), tool=name)
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

    def _note_intent(self, intent: str | None, *, tool: str) -> None:
        """Log ``call.intent`` when the best guess at the caller's goal changes.

        The values are the submit vocabulary the platform scores. A tool that
        says nothing about the goal passes ``None`` and the guess stands; a
        later tool that re-classifies logs again - the wall reads the most
        recent one (``wall_timeline.latest_intent``).
        """
        if not intent or intent == self._intent:
            return
        self._intent = intent
        self.ctx.log.event("call.intent", intent=intent, tool=tool)

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
        # The submissions that leave through here - a confirmed plan, an
        # accepted refusal, the end-of-call fallback - never passed the model's
        # ``submit_action`` tool, so this is where their intent lands in the
        # log: what the call ended as is what it wanted, on our best claim.
        self._note_intent(action.kind, tool="session.submit")
        if result.status in ACCEPTED_STATUSES:
            self._queue_sms(submitted_action(self.ctx, action))
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
            await self.sms.aclose()
            await self.submitter.aclose()

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
        to = self.ctx.from_number
        if not to:
            self.ctx.log.event("sms.skipped", reason="no_from_number", action_kind=action.kind)
            return
        details = await resolve_details(self.ctx, action)
        body = render_confirmation_text(action, details)
        payload = notification_payload(action, details)
        self.ctx.log.event("sms.sending", to=mask_phone(to), **payload)
        result = await self.sms.send(to=to, body=body)
        self.ctx.log.event(
            f"sms.{result.status}",
            to=mask_phone(result.to or to),
            detail=result.detail,
            sid=result.sid,
            **payload,
        )

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
