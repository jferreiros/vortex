"""One ``CallSession`` per WebSocket. Nothing in here is shared between calls.

The session owns:
- the ``ToolContext`` every tool receives (call_id, clock, clinic, log, submitter)
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

from vortex.clinic import make_clinic_client
from vortex.clinic.client import ClinicApi
from vortex.contract import MADRID, Action, NoAction, SubmitInput, SubmitResult, ToolContext
from vortex.line.submit import DryRunSubmitClient, SubmitApi, SubmitClient, submit_action
from vortex.line.twilio import StartPayload
from vortex.observability.calllog import CallLog
from vortex.settings import Settings, get_settings


@dataclass
class CallSession:
    settings: Settings
    start: StartPayload
    ctx: ToolContext
    submitter: SubmitApi
    media_frames_in: int = 0
    media_frames_out: int = 0
    submitted: list[SubmitResult] = field(default_factory=list)
    _closed: bool = False

    @property
    def call_id(self) -> str:
        return self.ctx.call_id

    @property
    def stream_sid(self) -> str:
        return self.start.stream_sid

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

    async def submit(self, action: Action) -> SubmitResult:
        result = await submit_action(self.ctx, SubmitInput(action=action))
        self.submitted.append(result)
        return result

    @property
    def has_accepted_submission(self) -> bool:
        return any(r.status in ("accepted", "duplicate", "dry_run") for r in self.submitted)

    async def close(self, reason: str = "socket_closed", **extra: Any) -> None:
        """End-of-call bookkeeping. Safe to call twice."""
        if self._closed:
            return
        self._closed = True
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

        TODO(line): decide the fallback with the team. Options: keep
        ``NoAction(out_of_scope)``, pick the reason from the last rejection
        the tools returned, or resubmit a prepared-but-unsent action from
        ``ctx.state``. Whatever it is, it must go out within the window.
        """
        if self.has_accepted_submission:
            return
        self.ctx.log.event("submit.fallback", why="no accepted submission when the call ended")
        await self.submit(NoAction(reason="out_of_scope"))
