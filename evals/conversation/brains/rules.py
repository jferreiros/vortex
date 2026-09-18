"""The rules brain: a deterministic reference receptionist.

It never reads ``says``. It reads the ``means`` annotations of the script and
follows the flow the system prompt describes: identify, check, find slots,
prepare, submit exactly once per thing done. Later annotations override earlier
ones, so the *final* stated request wins by construction.

What it proves: that the tools, threaded together the way the prompt tells the
model to thread them, produce the accepted action for each script. What it
cannot prove: that the model would have made those calls. The report says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from evals.conversation.brains.base import Trace
from evals.conversation.scenario import CallerTurn, Scenario
from vortex.conversation.prompt import GREETING
from vortex.tools import ToolError

_ID_FIELDS = ("name", "date_of_birth", "national_id", "phone")


@dataclass
class _State:
    caller: dict[str, Any] = field(default_factory=dict)
    patient: dict[str, Any] = field(default_factory=dict)  # third party, when given
    request: dict[str, Any] = field(default_factory=dict)
    register: dict[str, Any] = field(default_factory=dict)
    policy: str | None = None
    refuse: str | None = None
    declined: bool = False
    accepted: bool = False
    record: dict[str, Any] | None = None  # the identified patient record
    decided: bool = False


class RulesBrain:
    name = "rules"

    def __init__(self) -> None:
        self._state = _State()
        self._scenario: Scenario | None = None

    async def start(self, scenario: Scenario, trace: Trace) -> None:
        self._state = _State()
        self._scenario = scenario
        trace.say("assistant", GREETING)

    # ---- hearing ---------------------------------------------------------

    async def hear(self, turn: CallerTurn, trace: Trace) -> str:
        s = self._state
        m = turn.means
        if turn.says:
            trace.say("user", turn.says)
        if m.get("adversarial"):
            s.refuse = "out_of_scope"
            return self._reply(
                trace, "Lo siento, no puedo ayudarle con eso. ¿Desea pedir una cita?"
            )
        if m.get("silence_secs") or turn.silence_secs:
            return self._reply(trace, "¿Sigue ahí?")
        if m.get("off_topic"):
            return self._reply(trace, "Entiendo. Volvamos a la cita, si le parece.")
        for key in ("identify", "patient", "request", "register"):
            if m.get(key):
                getattr(s, "caller" if key == "identify" else key).update(m[key])
        if m.get("clear"):
            for key in m["clear"]:
                s.caller.pop(key, None)
                s.patient.pop(key, None)
                s.request.pop(key, None)
        if m.get("policy"):
            s.policy = m["policy"]
        if m.get("decline"):
            s.declined = True
        if m.get("accept"):
            s.accepted = True

        # Identify as soon as there is enough to look someone up.
        subject = s.patient or s.caller
        if s.record is None and any(subject.get(f) for f in _ID_FIELDS):
            await self._identify(subject, trace)

        if s.record is None and not s.register and subject:
            missing = self._second_field(subject)
            if missing:
                return self._reply(trace, f"¿Me confirma su {missing}, por favor?")
        if m.get("end") or m.get("accept"):
            await self._decide(trace)
            return self._reply(trace, "Perfecto. Queda anotado. Gracias por llamar, hasta luego.")
        return self._reply(trace, "Muy bien. ¿Algo más que deba saber?")

    async def hangup(self, trace: Trace) -> None:
        if not self._state.decided:
            await self._decide(trace)

    # ---- helpers -----------------------------------------------------------

    def _reply(self, trace: Trace, text: str) -> str:
        trace.say("assistant", text)
        return text

    @staticmethod
    def _second_field(subject: dict[str, Any]) -> str | None:
        given = [f for f in _ID_FIELDS if subject.get(f)]
        if len(given) >= 2:
            return None
        for f in ("date_of_birth", "national_id", "phone"):
            if f not in given:
                return {
                    "date_of_birth": "fecha de nacimiento",
                    "national_id": "DNI",
                    "phone": "teléfono",
                }[f]
        return None

    async def _identify(self, subject: dict[str, Any], trace: Trace) -> None:
        args = {f: subject[f] for f in _ID_FIELDS if subject.get(f)}
        try:
            res = await trace.call("find_patient", args)
        except ToolError:
            return
        if res["status"] == "found":
            self._state.record = res["patient"]
        elif res["status"] == "ambiguous" and len(args) >= 2:
            # Nothing else to ask for in the script: keep the first candidate only if unique by dob.
            self._state.record = None
        elif res["status"] == "not_found":
            self._state.record = None

    async def _submit(self, trace: Trace, action: dict[str, Any]) -> None:
        await trace.call("submit_action", {"action": action})

    async def _decide(self, trace: Trace) -> None:
        s = self._state
        if s.decided:
            return
        s.decided = True
        if s.refuse:
            await self._submit(trace, {"kind": "no-action", "reason": s.refuse})
            return

        req = s.request
        complaint = req.get("complaint")
        specialty = req.get("specialty_id")
        if complaint:
            route = await trace.call("triage", {"complaint": complaint})
            if route.get("emergency"):
                await self._submit(trace, {"kind": "escalate", "reason": "medical_emergency"})
                return
            specialty = specialty or route.get("specialty_id")

        subject = s.patient or s.caller
        if s.record is None and subject:
            await self._identify(subject, trace)
        if s.record is None:
            if s.register:
                check = await trace.call(
                    "validate_national_id", {"value": s.register.get("national_id", "")}
                )
                reg = await trace.call(
                    "build_registration", {**s.register, "national_id": check["normalized"]}
                )
                if reg.get("action"):
                    await self._submit(trace, reg["action"])
                else:
                    await self._submit(
                        trace, {"kind": "no-action", "reason": reg["rejection"]["reason"]}
                    )
                return
            await self._submit(trace, {"kind": "no-action", "reason": "patient_not_found"})
            return
        if s.declined and not req.get("intent"):
            await self._submit(trace, {"kind": "no-action", "reason": "out_of_scope"})
            return

        patient_id = s.record["patient_id"]
        intent = req.get("intent", "book")
        if intent == "cancel":
            await self._cancel(trace, patient_id)
            return
        if intent == "reschedule":
            await self._reschedule(trace, patient_id)
            return
        if intent == "question":
            await self._submit(trace, {"kind": "no-action", "reason": "out_of_scope"})
            return

        # ---- booking ---------------------------------------------------------
        provider_id = None
        if req.get("provider"):
            match = await trace.call(
                "find_provider", {"spoken_name": req["provider"], "specialty_id": specialty}
            )
            if match["status"] == "found":
                provider_id = match["provider"]["provider_id"]
                specialty = specialty or match["provider"]["specialty_id"]
            elif match["status"] == "ambiguous" and match["candidates"]:
                pick = next(
                    (c for c in match["candidates"] if c["specialty_id"] == specialty),
                    match["candidates"][0],
                )
                provider_id = pick["provider_id"]
                specialty = specialty or pick["specialty_id"]
            elif match["status"] == "on_leave":
                specialty = specialty or (match.get("provider") or {}).get("specialty_id")
                if not specialty:
                    await self._submit(trace, {"kind": "no-action", "reason": "provider_on_leave"})
                    return
                trace.notes.append("named provider on leave: redirecting inside the specialty")
            else:
                reason = (match.get("rejection") or {}).get("reason", "provider_not_found")
                await self._submit(trace, {"kind": "no-action", "reason": reason})
                return
        if not specialty:
            await self._submit(trace, {"kind": "no-action", "reason": "out_of_scope"})
            return

        location_id = req.get("location_id")
        if req.get("address") and not location_id:
            near = await trace.call(
                "nearest_location", {"address": req["address"], "specialty_id": specialty}
            )
            location_id = near.get("location_id")

        insurer = s.record.get("insurer") or None
        verdict = await trace.call(
            "check_eligibility",
            {
                "patient_id": patient_id,
                "specialty_id": specialty,
                "provider_id": provider_id,
                "location_id": location_id,
                "insurer": insurer,
            },
        )
        if not verdict["allowed"]:
            if s.policy and s.policy != insurer:
                verdict = await trace.call(
                    "check_eligibility",
                    {
                        "patient_id": patient_id,
                        "specialty_id": specialty,
                        "provider_id": provider_id,
                        "location_id": location_id,
                        "insurer": s.policy,
                    },
                )
                if verdict["allowed"]:
                    insurer = s.policy
            if not verdict["allowed"] and verdict.get("redirect_to"):
                provider_id = verdict["redirect_to"][0]["provider_id"]
                trace.notes.append(f"redirected to {provider_id}")
            elif not verdict["allowed"]:
                reason = (verdict.get("rejection") or {}).get("reason", "out_of_scope")
                await self._submit(trace, {"kind": "no-action", "reason": reason})
                return

        window = None
        if req.get("when"):
            window = await trace.call(
                "resolve_date", {"phrase": req["when"], "part_of_day": req.get("part_of_day")}
            )
            if window.get("rejection"):
                await self._submit(
                    trace, {"kind": "no-action", "reason": window["rejection"]["reason"]}
                )
                return
        elif req.get("part_of_day"):
            window = await trace.call(
                "resolve_date", {"phrase": "tomorrow", "part_of_day": req["part_of_day"]}
            )
        today = trace.ctx.now.date()
        args: dict[str, Any] = {
            "patient_id": patient_id,
            "specialty_id": specialty,
            "provider_id": provider_id,
            "location_id": location_id,
            "date_from": window["date_from"] if window else (today + timedelta(1)).isoformat(),
            "date_to": window["date_to"] if window else (today + timedelta(14)).isoformat(),
            "time_from": window.get("time_from") if window else None,
            "time_to": window.get("time_to") if window else None,
            "insurer": insurer,
            "language": req.get("language"),
        }
        avail = await trace.call("find_slots", {k: v for k, v in args.items() if v is not None})
        if avail.get("rejection"):
            await self._submit(trace, {"kind": "no-action", "reason": avail["rejection"]["reason"]})
            return
        if not avail["slots"]:
            if avail.get("blocked"):
                reason = avail["blocked"][0]["reason"]
            else:
                reason = "no_availability"
            await self._submit(trace, {"kind": "no-action", "reason": reason})
            return
        booking = await trace.call(
            "prepare_booking",
            {"patient_id": patient_id, "slot": avail["slots"][0], "policy_id": insurer or ""},
        )
        if booking.get("action"):
            await self._submit(trace, booking["action"])
        else:
            await self._submit(
                trace, {"kind": "no-action", "reason": booking["rejection"]["reason"]}
            )

    async def _pick_appointments(self, trace: Trace, patient_id: str) -> list[dict[str, Any]]:
        diary = await trace.call("list_appointments", {"patient_id": patient_id})
        appts = diary["appointments"]
        ref = self._state.request.get("appointment_ref")
        if not appts or ref in (None, "first", "mine", "my appointment"):
            return appts[:1]
        if ref == "all":
            return appts
        chosen = [
            a
            for a in appts
            if ref in (a["appointment_id"], a["provider_id"])
            or str(a["start"]).startswith(str(ref))
        ]
        return chosen or appts[:1]

    async def _cancel(self, trace: Trace, patient_id: str) -> None:
        s = self._state
        targets: list[tuple[str, dict[str, Any]]] = [
            (patient_id, a) for a in await self._pick_appointments(trace, patient_id)
        ]
        # "mine and my son's": a second person in the script.
        if s.patient and s.caller and s.patient != s.caller:
            other = await trace.call(
                "find_patient", {f: s.caller[f] for f in _ID_FIELDS if s.caller.get(f)}
            )
            if other["status"] == "found":
                other_id = other["patient"]["patient_id"]
                targets.extend(
                    (other_id, a) for a in await self._pick_appointments(trace, other_id)
                )
        if not targets:
            await self._submit(trace, {"kind": "no-action", "reason": "out_of_scope"})
            return
        for pid, appt in targets:
            res = await trace.call(
                "prepare_cancel", {"appointment_id": appt["appointment_id"], "patient_id": pid}
            )
            if res.get("action"):
                await self._submit(trace, res["action"])
            else:
                await self._submit(
                    trace, {"kind": "no-action", "reason": res["rejection"]["reason"]}
                )

    async def _reschedule(self, trace: Trace, patient_id: str) -> None:
        s = self._state
        appts = await self._pick_appointments(trace, patient_id)
        if not appts:
            await self._submit(trace, {"kind": "no-action", "reason": "out_of_scope"})
            return
        appt = appts[0]
        req = s.request
        window = await trace.call(
            "resolve_date",
            {"phrase": req.get("when", "tomorrow"), "part_of_day": req.get("part_of_day")},
        )
        avail = await trace.call(
            "find_slots",
            {
                "patient_id": patient_id,
                "provider_id": appt["provider_id"],
                "date_from": window["date_from"],
                "date_to": window["date_to"],
                **({"time_from": window["time_from"]} if window.get("time_from") else {}),
                **({"time_to": window["time_to"]} if window.get("time_to") else {}),
            },
        )
        if not avail["slots"]:
            await self._submit(trace, {"kind": "no-action", "reason": "no_availability"})
            return
        res = await trace.call(
            "prepare_reschedule",
            {
                "appointment_id": appt["appointment_id"],
                "slot": avail["slots"][0],
                "policy_id": s.record.get("insurer") or "",
            },
        )
        if res.get("action"):
            await self._submit(trace, res["action"])
        else:
            await self._submit(trace, {"kind": "no-action", "reason": res["rejection"]["reason"]})
