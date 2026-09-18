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

import json
from typing import Protocol

import httpx

from vortex.contract import (
    Action,
    SubmitInput,
    SubmitResult,
    ToolContext,
    action_payload,
    action_route,
)

_SENT_KEY = "submit.fingerprints"


def _fingerprint(action: Action) -> str:
    payload = action_payload(action, call_id="")
    payload.pop("call_id", None)
    return json.dumps({"route": action_route(action), "body": payload}, sort_keys=True, default=str)


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


async def submit_action(ctx: ToolContext, args: SubmitInput) -> SubmitResult:
    """The ``submit_action`` tool. Sends through the call's own submit client."""
    if ctx.submitter is None:
        return SubmitResult(status="error", detail="no submitter on this call context")
    seen = ctx.state.setdefault(_SENT_KEY, [])
    key = _fingerprint(args.action)
    if key in seen:
        result = SubmitResult(
            status="duplicate", detail="already submitted this action this call"
        )
        ctx.log.event("submit.duplicate", route=action_route(args.action), detail=result.detail)
        return result
    seen.append(key)
    route = action_route(args.action)
    payload = action_payload(args.action, ctx.call_id)
    ctx.log.event("submit.sent", route=route, payload=payload)
    result = await ctx.submitter.submit(ctx.call_id, args.action)
    ctx.log.action_submitted(route, payload, result)
    return result
