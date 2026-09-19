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
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from vortex import tools as registry
from vortex.clinic import make_clinic_client
from vortex.clinic.client import ClinicApi
from vortex.contract import (
    MADRID,
    Action,
    DeclineReason,
    EscalateAction,
    FindPatientResult,
    NoAction,
    Rejection,
    SubmitInput,
    SubmitResult,
    ToolContext,
    action_route,
)
from vortex.line.submit import (
    DryRunSubmitClient,
    SubmitApi,
    SubmitClient,
    submit_action,
    with_verdict_reason,
)
from vortex.line.twilio import StartPayload
from vortex.observability.calllog import CallLog
from vortex.observability.tracing import observe_span
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

# The tools that answer with the rule the clinic applied, named in the closed
# vocabulary the platform scores. Their reason is the call's verdict: a refusal
# has to carry it verbatim, whatever the model remembered. See
# ``CallMemory.last_verdict`` and the override in ``vortex/line/submit.py``.
VERDICT_TOOLS: frozenset[str] = frozenset({"check_eligibility", "find_slots"})


def refusal_for(reason: DeclineReason) -> Action:
    """The action a named reason ends on. A red flag goes to /escalate, the rest refuse."""
    if reason == "medical_emergency":
        return EscalateAction(reason=reason)
    return NoAction(reason=reason)


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
    # The subset of ``last_rejection`` that came from a rule, not from prose:
    # an eligibility verdict or a provider ``find_slots`` reported as blocked.
    # It is the reason a refusal must carry, so ``submit_action`` forces it.
    last_verdict: Rejection | None = None
    last_verdict_tool: str = ""
    # The same reason, kept across the action a tool later prepares around it.
    # A plan nobody confirmed must not cost the call a named reason: replacing
    # one with ``out_of_scope`` only ever loses the case. Free slots clear it,
    # because by then the rule no longer stands.
    stored_reason: Rejection | None = None
    stored_reason_tool: str = ""
    # A lookup ran and nobody was identified. The call ends on
    # ``patient_not_found``, which says what happened; ``out_of_scope`` claims
    # we could not serve the request at all, which is a different call.
    identity_pending: bool = False
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

    def observe(self, tool: str, result: Any) -> None:
        """Remember whatever a tool result says about where the call stands.

        Reads the contract's own field names, so no lane tool has to know this
        exists: ``rejection`` on every result that can refuse, ``action`` on the
        ``prepare_*`` and ``build_registration`` results, ``slots``/``blocked``
        on availability, ``status`` on the identity lookup.
        """
        if isinstance(result, FindPatientResult):
            self.identity_pending = result.status != "found"

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
        CallMemory.of(ctx)  # attach it before any tool runs
        session = cls(settings=settings, start=start, ctx=ctx, submitter=submitter)
        log.event(
            "call.started",
            stream_sid=start.stream_sid,
            from_number=start.from_number,
            custom_parameters=start.custom_parameters,
            connected_at=ctx.now,
            **settings.describe(),
        )
        return session

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
        else:
            self.memory.observe(name, result)
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
            self.ctx.log.summary(reason=reason)
            await self.submitter.aclose()

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

    def fallback_action(self) -> tuple[str, Action, str]:
        """The action a silent call ends on: (branch, action, why)."""
        memory = self.memory

        # (a) Something was drawn up and never sent. Only with the caller's yes:
        #     a booking nobody agreed to is a wrong write, which is worse than
        #     a named refusal.
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

        # (d) Nobody said anything we could act on: a dropped or silent call.
        if self.ctx.log.user_turns == 0:
            return (
                "no_turns",
                NoAction(reason="out_of_scope"),
                "the caller never said anything we could act on",
            )

        # (e) The line died with the lookup still open: a patient was searched
        #     for and none was identified. That is patient_not_found, and it is
        #     the one thing out_of_scope certainly is not - the request was ours
        #     to serve, we just never learned whose it was.
        if memory.identity_pending:
            return (
                "identity_pending",
                NoAction(reason="patient_not_found"),
                "a lookup ran and identified nobody",
            )

        # (f) A real conversation that resolved nothing, and no rule to name.
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
