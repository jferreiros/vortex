"""Rebuild every recorded call from JSONL logs into a readable rundown.

Usage: python scripts/call_rundown.py <calls_dir> [call_id_substring]

Example: python scripts/call_rundown.py evals/results/conversation/calls p10
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

# tool name -> clinic endpoint(s) it triggers (from vortex/*/tools.py)
ENDPOINTS = {
    "find_patient": (
        "GET /api/v1/directory (+ GET /patients/{id}/appointments?when=past in background)"
    ),
    "validate_national_id": "local (DNI/NIE check letter, no API)",
    "build_registration": "GET /api/v1/clinic (catalogue: insurers)",
    "resolve_date": "GET /api/v1/clinic (catalogue: closures)",
    "find_slots": "GET /api/v1/availability (+ catalogue fallback)",
    "list_appointments": "stub - should be GET /patients/{id}/appointments",
    "prepare_booking": "GET /api/v1/clinic + GET /api/v1/availability (re-verify slot)",
    "prepare_reschedule": "stub",
    "prepare_cancel": "stub",
    "check_eligibility": "GET /api/v1/availability + GET /api/v1/clinic",
    "triage": "local (symptom rules, no API)",
    "nearest_location": "local/stub",
    "find_provider": "GET /api/v1/clinic (catalogue: providers)",
    "submit_action": "POST /api/v1/submit/<route>",
}


def fix(s):
    """Repair UTF-8 read as cp1252 (Windows scenario load)."""
    if not isinstance(s, str):
        return s
    try:
        return s.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def short(v, n=300):
    s = json.dumps(v, ensure_ascii=False, default=str)
    s = fix(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    calls_dir = Path(sys.argv[1])
    filt = sys.argv[2] if len(sys.argv) > 2 else ""
    files = sorted(calls_dir.glob("*.jsonl"))
    tool_stats = defaultdict(list)
    for f in files:
        cid = f.stem
        if filt and filt not in cid:
            continue
        events = [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines()]
        print("=" * 100)
        print(f"CALL {cid}   ({len(events)} events)")
        print("=" * 100)
        last_user = "(call connected)"
        t0 = None
        for ev in events:
            ts = ev["ts"].split("T")[1][:12]
            if t0 is None:
                t0 = ts
            kind = ev["kind"]
            if kind == "turn.user":
                last_user = fix(ev["text"])
                print(f"[{ts}] CALLER   : {fix(ev['text'])}")
            elif kind == "turn.assistant":
                print(f"[{ts}] AGENT    : {fix(ev['text'])}")
            elif kind == "tool.called":
                tool = ev["tool"]
                print(f"[{ts}]   -> TOOL {tool}  args={short(ev['args'], 200)}")
                print(f"             triggered by: \"{last_user[:110]}\"")
                print(f"             hits: {ENDPOINTS.get(tool, '?')}")
            elif kind == "tool.returned":
                tool_stats[ev["tool"]].append(ev["ms"])
                print(f"[{ts}]   <- {ev['tool']}  {ev['ms']} ms  result={short(ev['result'], 260)}")
            elif kind == "tool.failed":
                print(f"[{ts}]   !! {ev['tool']} FAILED: {ev['error']}")
            elif kind in ("submit.sent", "submit.result"):
                body = {k: v for k, v in ev.items() if k not in ("ts", "call_id", "kind")}
                print(f"[{ts}]   ** {kind}: {short(body, 260)}")
            else:
                body = {k: v for k, v in ev.items() if k not in ("ts", "call_id", "kind")}
                print(f"[{ts}]   .. {kind}: {short(body, 200)}")
        print()

    if not filt:
        print("=" * 100)
        print("LATENCY PER TOOL (ms, in-process tool time; FakeClinicClient, no network)")
        print("=" * 100)
        for tool, ms in sorted(tool_stats.items(), key=lambda kv: -sum(kv[1])):
            print(
                f"{tool:24s} n={len(ms):3d}  total={sum(ms):7.1f}  "
                f"avg={sum(ms) / len(ms):5.1f}  max={max(ms):5.1f}"
            )


if __name__ == "__main__":
    main()
