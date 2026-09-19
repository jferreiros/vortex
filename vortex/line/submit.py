"""The submit client: POST /api/v1/submit/<action> inside the 30-second window.

Two implementations share one interface:

- ``SubmitClient``       live HTTP with ``X-Api-Key``.
- ``DryRunSubmitClient`` logs what would have been sent. Used with no key.

Response codes (call contract §2):
  200 accepted · 409 identical action already accepted (a retry; fine)
  410 window closed · 404 unknown call_id · 422 malformed body (nothing recorded)

The window opens when the platform opens the call and closes 30 s after the
socket closes. Sending early is never a rejection. A 200 acknowledges receipt,
not a pass.
"""

from __future__ import annotations

from typing import Protocol

import httpx

from vortex.contract import (
    Action,
    EscalateAction,
    NoAction,
    SubmitInput,
    SubmitResult,
    ToolContext,
    action_payload,
    action_route,
)


class SubmitApi(Protocol):
    async def submit(self, call_id: str, action: Action) -> SubmitResult: ...

    async def aclose(self) -> None: ...


class SubmitClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 8.0):
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-Api-Key": api_key},
            timeout=timeout,
        )

    async def submit(self, call_id: str, action: Action) -> SubmitResult:
        route = action_route(action)
        payload = action_payload(action, call_id)
        try:
            response = await self._http.post(route, json=payload)
        except httpx.HTTPError as exc:
            return SubmitResult(status="error", detail=f"{type(exc).__name__}: {exc}")
        code = response.status_code
        detail = response.text[:300]
        if code == 200:
            return SubmitResult(status="accepted", http_status=code, detail=detail)
        if code == 409:
            return SubmitResult(status="duplicate", http_status=code, detail=detail)
        if code == 410:
            return SubmitResult(status="late", http_status=code, detail=detail)
        if code == 404:
            return SubmitResult(status="unknown_call", http_status=code, detail=detail)
        if code == 422:
            return SubmitResult(status="rejected", http_status=code, detail=detail)
        return SubmitResult(status="error", http_status=code, detail=detail)

    async def aclose(self) -> None:
        await self._http.aclose()


class DryRunSubmitClient:
    """No key, no network. Records what would have gone out."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    async def submit(self, call_id: str, action: Action) -> SubmitResult:
        self.sent.append((action_route(action), action_payload(action, call_id)))
        return SubmitResult(status="dry_run", detail="no PLATFORM_API_KEY: not sent")

    async def aclose(self) -> None:
        return None


def with_verdict_reason(ctx: ToolContext, action: Action) -> Action:
    """Refuse with the rule the clinic applied, not with the model's paraphrase.

    ``reason`` is scored against a closed vocabulary, so a near neighbour is
    worth exactly what silence is worth: on call ``c9f087a0``
    ``check_eligibility`` answered ``location_not_covered`` (ASISA does not
    cover physiotherapy at that site) and the model submitted
    ``specialty_not_covered``, losing the case. Whenever the call holds a
    verdict from the rules - an eligibility refusal or a blocked provider from
    ``find_slots`` - it wins.

    Only NO_ACTION and ESCALATE carry a reason; every other action is returned
    untouched. The verb is the model's: a stored verdict never turns a refusal
    into an escalation or back. The swap is pure, so the session can ask what
    will go out; ``submit_action`` is what logs it.
    """
    if not isinstance(action, (NoAction, EscalateAction)):
        return action
    from vortex.line.session import CallMemory  # late: session imports this module

    verdict = CallMemory.of(ctx).last_verdict
    if verdict is None or verdict.reason == action.reason:
        return action
    forced = action.model_copy(update={"reason": verdict.reason})
    assert forced.kind == action.kind
    return forced


async def submit_action(ctx: ToolContext, args: SubmitInput) -> SubmitResult:
    """The ``submit_action`` tool. Sends through the call's own submit client."""
    if ctx.submitter is None:
        return SubmitResult(status="error", detail="no submitter on this call context")
    action = with_verdict_reason(ctx, args.action)
    if action is not args.action:
        ctx.log.event(
            "submit.reason_override",
            route=action_route(action),
            model_reason=args.action.reason,  # type: ignore[union-attr]
            reason=action.reason,  # type: ignore[union-attr]
        )
    route = action_route(action)
    payload = action_payload(action, ctx.call_id)
    ctx.log.event("submit.sent", route=route, payload=payload)
    result = await ctx.submitter.submit(ctx.call_id, action)
    ctx.log.action_submitted(route, payload, result)
    return result
