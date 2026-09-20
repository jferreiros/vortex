"""Team Discord cards for finished calls. Counts and clinic ids; never PII."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from vortex.observability.view import CallCard, build_calls

log = logging.getLogger(__name__)

WALL = "https://vortex.203.0.113.20.sslip.io/wall"
LANGFUSE_PROJECT_URL = "https://cloud.langfuse.com/project/cmu7le5go05ffad0gp2xjvxjo"
_TRUE = ("1", "true", "yes", "on")
_SAFE_ACTION_KEYS = (
    "kind",
    "reason",
    "specialty_id",
    "location_id",
    "provider_id",
    "appointment_type_id",
    "slot",
)
_COLOUR = {
    "booked": 0x3DDC84,
    "registered": 0x3DDC84,
    "rescheduled": 0x3DDC84,
    "cancelled": 0x3DDC84,
    "escalated": 0xEAB619,
    "refused": 0xEAB619,
    "ended": 0x888888,
    "live": 0x888888,
    "crashed": 0xE23D4A,
}
_PII_KEYS = frozenset(
    {
        "given_name",
        "first_surname",
        "second_surname",
        "national_id",
        "date_of_birth",
        "phone",
        "email",
        "from_number",
        "patient_name",
        "said",
    }
)
_PII_VALUE = re.compile(r"\b\d{8}[A-Za-z]\b|\b[XYZxyz]\d{7}[A-Za-z]\b|\+34\d{9}")


def enabled() -> bool:
    if (
        os.environ.get("PYTEST_CURRENT_TEST")
        and os.environ.get("DISCORD_NOTIFY_IN_TESTS", "").strip().lower() not in _TRUE
    ):
        return False
    return bool(webhook_url())


def webhook_url() -> str:
    return (
        os.environ.get("DISCORD_CALLS_WEBHOOK_URL", "").strip()
        or os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    )


def wall_url() -> str:
    return os.environ.get("VORTEX_WALL_URL", "").strip() or WALL


def langfuse_url() -> str:
    return os.environ.get("LANGFUSE_PROJECT_URL", "").strip() or LANGFUSE_PROJECT_URL


def _kind_from_route(route: str) -> str:
    if not route:
        return ""
    return route.rstrip("/").rsplit("/", 1)[-1]


def _safe_action(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return {
        key: payload[key]
        for key in _SAFE_ACTION_KEYS
        if key in payload and payload[key] not in (None, "")
    }


def _duration_label(ms: float | None) -> str:
    if ms is None:
        return "?"
    if ms >= 1000:
        return f"{ms / 1000:.1f}s"
    return f"{ms:.0f}ms"


def card_from_session(session: Any) -> dict[str, Any]:
    call_log = session.ctx.log
    last = call_log.actions[-1] if call_log.actions else {}
    route = str(last.get("route") or "")
    payload = last.get("payload") if isinstance(last.get("payload"), dict) else {}
    result = last.get("result")
    status = ""
    if isinstance(result, dict):
        status = str(result.get("status") or "")
    started = getattr(call_log, "_started", None)
    duration_ms = round((time.monotonic() - started) * 1000) if started is not None else None
    kind = _kind_from_route(route) or str(payload.get("kind") or "")
    reason = str(payload.get("reason") or getattr(session, "end_reason", "") or "")
    settings = session.settings
    return {
        "call_id": session.call_id,
        "status": "crashed" if reason == "crashed" else (kind or "ended"),
        "kind": kind,
        "reason": reason,
        "submit_status": status,
        "duration_ms": duration_ms,
        "turns": call_log.turns,
        "user_turns": call_log.user_turns,
        "tools": call_log.tool_calls,
        "tool_names": [],
        "action": _safe_action(payload),
        "voice": "pipecat" if settings.voice_is_pipecat else "stub",
        "clinic": "live" if settings.clinic_is_live else "fake",
        "llm": f"{settings.llm_provider}/{settings.llm_model}",
    }


def card_from_view(card: CallCard) -> dict[str, Any]:
    kind = card.action_kind or ""
    status = "crashed" if card.reason == "crashed" else card.status
    return {
        "call_id": card.call_id,
        "status": status,
        "kind": kind,
        "reason": card.decline_reason or card.reason or "",
        "submit_status": card.submit_status or "",
        "duration_ms": card.duration_ms,
        "turns": len(card.turns),
        "user_turns": sum(1 for turn in card.turns if turn.role == "user"),
        "tools": len(card.tools),
        "tool_names": [step.name for step in card.tools],
        "action": _safe_action(card.action_payload),
        "voice": card.voice or "",
        "clinic": card.clinic or "",
        "llm": "",
    }


def cards_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PII-free cards for a list of call events, whatever read produced them."""
    return [card_from_view(card) for card in build_calls(events)]


def cards_from_store(*, limit: int = 20000) -> list[dict[str, Any]]:
    """The last ``limit`` events in ``public.call_events``, as digest cards."""
    from vortex.observability import supabase_log

    return cards_from_events(supabase_log.fetch_recent(limit) or [])


def assert_no_pii(payload: Any) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in _PII_KEYS:
                raise AssertionError(f"pii key leaked: {key}")
            assert_no_pii(value)
    elif isinstance(payload, list):
        for item in payload:
            assert_no_pii(item)
    elif isinstance(payload, str) and _PII_VALUE.search(payload):
        raise AssertionError("pii value leaked")


def _line(card: dict[str, Any]) -> str:
    mark = {
        "booked": "🟢",
        "registered": "🟢",
        "rescheduled": "🟢",
        "cancelled": "🟢",
        "escalated": "🟡",
        "refused": "🟡",
        "crashed": "🔴",
    }.get(str(card.get("status")), "⚪")
    kind = card.get("kind") or card.get("status") or "ended"
    reason = card.get("reason") or card.get("submit_status") or ""
    extra = f" · {reason}" if reason else ""
    tools = card.get("tools") or 0
    return (
        f"{mark} `{card.get('call_id')}` · **{kind}**{extra} · "
        f"{_duration_label(card.get('duration_ms'))} · {tools} tools"
    )


def webhook_body(card: dict[str, Any], *, wall: str | None = None) -> dict[str, Any]:
    wall = wall or wall_url()
    status = str(card.get("status") or "ended")
    langfuse = langfuse_url()
    description = _line(card)
    action = card.get("action") or {}
    if action:
        bits = [f"{key}={value}" for key, value in action.items()]
        description += "\n" + " · ".join(bits)
    meta = " · ".join(
        part
        for part in (
            card.get("clinic") or "",
            card.get("voice") or "",
            card.get("llm") or "",
        )
        if part
    )
    body = {
        "username": "Vortex calls",
        "content": f"Llamada lista · {card.get('kind') or status} · {wall}",
        "embeds": [
            {
                "title": (
                    f"{card.get('kind') or status} · {_duration_label(card.get('duration_ms'))}"
                ),
                "url": wall,
                "color": _COLOUR.get(status, _COLOUR["ended"]),
                "description": description[:3900],
                "footer": {
                    "text": f"{meta} · langfuse {langfuse}" if meta else f"langfuse {langfuse}"
                },
            }
        ],
    }
    assert_no_pii(body)
    return body


def digest_body(cards: list[dict[str, Any]], *, wall: str | None = None) -> dict[str, Any]:
    wall = wall or wall_url()
    if not cards:
        return {
            "username": "Vortex calls",
            "content": f"Ninguna llamada en el log. · {wall}",
        }
    counts: dict[str, int] = {}
    for card in cards:
        key = str(card.get("kind") or card.get("status") or "ended")
        counts[key] = counts.get(key, 0) + 1
    tally = " · ".join(f"{name} {n}" for name, n in sorted(counts.items()))
    lines = [_line(card) for card in cards[:40]]
    if len(cards) > 40:
        lines.append(f"… y {len(cards) - 40} más")
    crashed = any(card.get("status") == "crashed" for card in cards)
    booked = sum(1 for card in cards if card.get("status") in {"booked", "registered"})
    color = _COLOUR["crashed"] if crashed else (_COLOUR["booked"] if booked else _COLOUR["refused"])
    langfuse = langfuse_url()
    body = {
        "username": "Vortex calls",
        "content": f"**{len(cards)} llamadas** · {tally}\n{wall}",
        "embeds": [
            {
                "title": f"{len(cards)} llamadas",
                "url": wall,
                "color": color,
                "description": "\n".join(lines)[:3900],
                "footer": {"text": f"langfuse {langfuse}"},
            }
        ],
    }
    assert_no_pii(body)
    return body


def post(payload: dict[str, Any], *, url: str | None = None) -> bool:
    target = (url or webhook_url()).strip()
    if not target:
        return False
    request = urllib.request.Request(
        target,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "vortex-hackspain",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return 200 <= response.status < 300
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            time.sleep(1.5)
            try:
                with urllib.request.urlopen(request, timeout=15) as response:
                    return 200 <= response.status < 300
            except Exception:
                log.debug("discord retry failed", exc_info=True)
                return False
        log.debug("discord post failed", exc_info=True)
        return False
    except Exception:
        log.debug("discord post failed", exc_info=True)
        return False


def notify_session(session: Any) -> None:
    if not enabled():
        return
    try:
        payload = webhook_body(card_from_session(session))
    except Exception:
        log.debug("discord call card failed", exc_info=True)
        return
    threading.Thread(target=post, args=(payload,), daemon=True, name="discord-call").start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discord digest of the call log")
    parser.add_argument("--json", action="store_true", help="print the webhook body")
    parser.add_argument("--limit", type=int, default=20000)
    args = parser.parse_args(argv)
    cards = cards_from_store(limit=args.limit)
    body = digest_body(cards)
    if args.json:
        print(json.dumps(body, ensure_ascii=False))
        return 0
    print(json.dumps(body, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
