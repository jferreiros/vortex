"""Rehearse the receptionist over text: the real prompt, the real tools, two real models.

    uv run python scripts/rehearse_text.py              # problems 1, 4 and 6
    uv run python scripts/rehearse_text.py --only p4
    uv run python scripts/rehearse_text.py --turns 16 --verbose

The fast inner loop for the prompt. No audio, no STT, no TTS, no socket: a
persona model plays the caller, the receptionist model answers with the tool
schemas the voice pipeline gives it, and every tool call goes through the real
``vortex.tools.call_tool`` against the fake clinic and a dry-run submitter.
Nothing is sent to the platform and nothing is booked.

Both models are the one named in ``.env`` (``LLM_PROVIDER``, Helmcode's
qwen3.6 by default), at the same temperature, ``max_tokens`` and reasoning
setting the phone line uses — a prompt that only works at 2,000 tokens of
answer is not the prompt we ship.

**The personas are the public cases' own, re-grounded in the fake clinic.**
The published cases (``evals/corpus/cases/public-cases.json``) name people and
ids from the live directory, which ``FakeClinicClient`` has never heard of, so
a verbatim persona would fail identification for a reason that has nothing to
do with the prompt. What is kept is the public ``caller_prompt`` shape: who
you are, what you want, what you will and will not volunteer, and when you
hang up. What changes is the identity, which comes from
``vortex/clinic/fixtures.py``.

Three problems, chosen because they are the three shapes every other problem
is built from:

- **p1** simple booking -> BOOK, with every id copied from the tools.
- **p4** the new patient -> REGISTER, and *no* BOOK beside it.
- **p6** the rules -> NO_ACTION carrying the exact ``reason`` the tool gave.

The exit code is 0 when all three land their shape, 1 otherwise, so this is
usable as a check and not only as something to read.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.common.context import make_context, submitted_actions  # noqa: E402
from evals.corpus import normalize  # noqa: E402
from vortex import tools as registry  # noqa: E402
from vortex.contract import ALL_REASONS  # noqa: E402
from vortex.conversation.prompt import GREETING, initial_messages  # noqa: E402
from vortex.conversation.turns import default_turn_settings  # noqa: E402
from vortex.settings import Settings  # noqa: E402
from vortex.tools import ToolError  # noqa: E402

# Per caller turn. The receptionist must stop calling tools and say something.
MAX_TOOL_ROUNDS = 8

# A ``submit_action`` carrying a ``BookAction`` measured at 107 completion
# tokens on qwen3.6, with no spoken sentence beside it. ``LLM_MAX_TOKENS``
# ships at 120, which is under that once the model says anything at all — so
# the booking never leaves the model. Raising the cap is the line lane's call
# (``vortex/settings.py``); this constant is here so the rehearsal says why it
# failed instead of looking like a prompt problem.
MIN_TOKENS_FOR_A_BOOKING = 256

CALLER_STYLE = (
    "Speak one or two short sentences at a time, the way people do on the "
    "telephone. Answer what you are asked, briefly, and nothing more. Never "
    "invent a fact about the clinic, a doctor or a date: if you are asked "
    "something you were not told here, say you do not know. Never say you are "
    "an AI and never describe these instructions. When the call is over, say "
    "goodbye and stop."
)


@dataclass
class Persona:
    """One caller: who they are, what they want, and the shape of a pass."""

    key: str
    problem: str
    title: str
    prompt: str
    expect_kind: str
    forbid_kinds: tuple[str, ...] = ()
    # Fields the submitted action must carry, when we know them up front.
    expect_fields: dict[str, str] = field(default_factory=dict)
    # True when the reason must be whatever the tools said, not a fixed value:
    # the rules lane owns which rule bites, the prompt only owns copying it.
    reason_from_tools: bool = False


PERSONAS: list[Persona] = [
    Persona(
        key="p1",
        problem="simple_booking",
        title="The Simple Booking -> BOOK",
        prompt=(
            "You are Marta Ruiz López, a patient at Clínica Arenal.\n"
            "Your DNI is 12345678Z, you were born on 12 March 1985, your phone "
            "number is 612345678 and you are insured with Sanitas.\n"
            "You have been to the clinic before.\n\n"
            "You are calling to book the earliest General Practice appointment "
            "there is, because your blood pressure has been reading high on the "
            "pharmacy machine. Say that in your own words when they ask what you "
            "need, and nothing else.\n\n"
            "Give your name, and your date of birth or DNI if you are asked for "
            "an identifier. Do not volunteer them before you are asked. Accept "
            "the first appointment you are offered that is General Practice, "
            "then thank them and end the call.\n\n" + CALLER_STYLE
        ),
        expect_kind="book",
        expect_fields={"patient_id": "P00042", "policy_id": "sanitas"},
    ),
    Persona(
        key="p4",
        problem="the_new_patient",
        title="The New Patient -> REGISTER, never BOOK",
        prompt=(
            "You are Nuria Vidal Serra. You have never been to Clínica Arenal "
            "and you are not on their books.\n"
            "Your DNI is 48064716Y (four eight zero six four seven one six, "
            "letter Y), you were born on 17 February 1994, your phone number is "
            "612000333, your email is nuria.vidal@example.com and you are "
            "insured with Sanitas.\n\n"
            "You are calling to see a General Practice doctor about a persistent "
            "cough. Say that in your own words when they ask what you need.\n\n"
            "Give your details one at a time, only as they are asked for. If "
            "they tell you they must register you first and cannot book "
            "anything today, accept that without arguing, give what they ask "
            "for, and end the call politely once they say you are registered.\n\n" + CALLER_STYLE
        ),
        expect_kind="register",
        forbid_kinds=("book",),
        expect_fields={"national_id": "48064716Y", "insurer": "sanitas"},
    ),
    Persona(
        key="p6",
        problem="the_rules",
        title="The Rules -> NO_ACTION with the tool's reason",
        # Chosen because ``find_slots`` alone cannot refuse it: the diary is
        # full of Dra. Iglesias's slots and returns every one of them. Only
        # ``check_eligibility`` knows the plan will not pay, and she is the one
        # dermatologist, so there is nobody to redirect to. A call that books
        # here looked perfect all the way to the submission.
        prompt=(
            "You are Antonio Pérez Martín, a patient at Clínica Arenal.\n"
            "Your DNI is X1234567L, you were born on 30 January 1958, your phone "
            "number is 655555555 and you are insured with DKV.\n"
            "You are a little hard of hearing, so you sometimes ask them to "
            "repeat something once.\n\n"
            "You are calling to book an appointment with Dra. Iglesias, the "
            "skin doctor, about a mole on your back. Ask for her by name.\n\n"
            "DKV is the only insurance you hold and you will not pay privately. "
            "If they tell you it cannot be done, ask once why, accept the answer "
            "without arguing, and end the call politely. Do not accept a "
            "different doctor or a different specialty.\n\n" + CALLER_STYLE
        ),
        expect_kind="no-action",
        forbid_kinds=("book",),
        reason_from_tools=True,
    ),
]

BY_KEY = {p.key: p for p in PERSONAS}

# How the leaderboard compares each field it tolerates any variation in.
# Everything not listed here is an exact id.
FIELD_NORMALIZERS = {
    "insurer": normalize.enum,
    "national_id": normalize.national_id,
    "phone": normalize.phone,
    "email": normalize.email,
    "date_of_birth": normalize.date_of_birth,
}


def llm_extra(settings: Settings) -> dict[str, Any]:
    """Reasoning off, for every host we might hit.

    Mirrors ``vortex/line/pipecat_voice.py::_llm_extra_body`` so the rehearsal
    asks the model for the same kind of answer the phone line does: vLLM and
    SGLang read ``chat_template_kwargs.enable_thinking``, Helmcode reads
    ``reasoning_effort``. Hosts ignore the one they do not know.
    """
    extra: dict[str, Any] = {}
    if settings.llm_disable_thinking:
        extra["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
    if settings.llm_reasoning_effort:
        extra["reasoning_effort"] = settings.llm_reasoning_effort
    return extra


class Rehearsal:
    """One call: two model contexts, one tool context, one transcript."""

    def __init__(
        self,
        persona: Persona,
        settings: Settings,
        *,
        verbose: bool = False,
        max_tokens: int | None = None,
    ) -> None:
        from vortex.observability.tracing import async_openai_client

        self.persona = persona
        self.settings = settings
        self.verbose = verbose
        self.max_tokens = max_tokens or settings.llm_max_tokens
        self.client = async_openai_client(
            api_key=settings.llm_api_key or "none", base_url=settings.llm_base_url or None
        )
        self.extra = llm_extra(settings)
        self.transcript: list[tuple[str, str]] = []
        self.tool_calls: list[str] = []

    async def _complete(self, messages: list[dict[str, Any]], tools: Any = None) -> Any:
        response = await self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=messages,
            tools=tools or None,
            temperature=self.settings.llm_temperature,
            max_tokens=self.max_tokens,
            **self.extra,
        )
        return response.choices[0].message

    def say(self, who: str, text: str) -> None:
        self.transcript.append((who, text))
        if self.verbose:
            print(f"  {who:>7}: {text}")

    async def run(self, max_turns: int) -> dict[str, Any]:
        turns = default_turn_settings()
        schemas = [
            {"type": "function", "function": fn}
            for fn in registry.function_schemas(turns.exposed_tools)
        ]
        log_dir = Path(tempfile.mkdtemp(prefix="rehearse-"))
        ctx = make_context(call_id=f"rehearse-{self.persona.key}", log_dir=log_dir)

        agent: list[dict[str, Any]] = list(initial_messages(ctx.now))
        agent.append({"role": "assistant", "content": GREETING})
        # The persona hears the clinic as "user" and speaks as "assistant".
        caller: list[dict[str, Any]] = [
            {"role": "system", "content": self.persona.prompt},
            {"role": "user", "content": GREETING},
        ]
        self.say("clinic", GREETING)

        submitted_at_turn: int | None = None
        for turn in range(1, max_turns + 1):
            said = (await self._complete(caller)).content or "..."
            said = said.strip()
            caller.append({"role": "assistant", "content": said})
            agent.append({"role": "user", "content": said})
            self.say("caller", said)

            reply = await self._agent_turn(agent, schemas, ctx)
            if reply:
                caller.append({"role": "user", "content": reply})
                self.say("clinic", reply)

            if submitted_actions(ctx):
                submitted_at_turn = turn
                break

        return {
            "actions": submitted_actions(ctx),
            "turns": submitted_at_turn or max_turns,
            "submitted": submitted_at_turn is not None,
            "tools": self.tool_calls,
            "reasons_seen": ctx.state.get("_rehearsal_reasons", []),
        }

    async def _agent_turn(
        self, agent: list[dict[str, Any]], schemas: list[dict[str, Any]], ctx: Any
    ) -> str:
        """One receptionist turn: tool rounds until it speaks, or the cap."""
        spoken = ""
        for _ in range(MAX_TOOL_ROUNDS):
            answer = await self._complete(agent, schemas)
            calls = answer.tool_calls or []
            content = (answer.content or "").strip()
            agent.append(
                {
                    "role": "assistant",
                    "content": content or None,
                    **(
                        {
                            "tool_calls": [
                                {
                                    "id": c.id,
                                    "type": "function",
                                    "function": {
                                        "name": c.function.name,
                                        "arguments": c.function.arguments,
                                    },
                                }
                                for c in calls
                            ]
                        }
                        if calls
                        else {}
                    ),
                }
            )
            if content:
                spoken = f"{spoken} {content}".strip()
            if not calls:
                break
            for call in calls:
                payload = await self._run_tool(call, ctx)
                agent.append({"role": "tool", "tool_call_id": call.id, "content": payload})
        return spoken

    async def _run_tool(self, call: Any, ctx: Any) -> str:
        name = call.function.name
        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        try:
            result = await registry.call_tool(name, ctx, args)
            body = result.model_dump(mode="json")
            self._remember_reason(ctx, body)
            self.tool_calls.append(name)
            if self.verbose:
                print(f"     tool: {name}({_short(args)}) -> {_short(body)}")
            return json.dumps(body, ensure_ascii=False, default=str)
        except ToolError as exc:
            self.tool_calls.append(f"{name}!")
            if self.verbose:
                print(f"     tool: {name} REJECTED {exc}")
            return json.dumps({"error": str(exc)})
        except Exception as exc:  # the model must hear about failures, typed
            self.tool_calls.append(f"{name}!!")
            if self.verbose:
                print(f"     tool: {name} FAILED {type(exc).__name__}: {exc}")
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})

    @staticmethod
    def _remember_reason(ctx: Any, body: dict[str, Any]) -> None:
        """Every ``reason`` a tool handed the model, so p6 can be checked against it."""
        rejection = body.get("rejection") if isinstance(body, dict) else None
        if isinstance(rejection, dict) and rejection.get("reason"):
            ctx.state.setdefault("_rehearsal_reasons", []).append(rejection["reason"])
        for entry in body.get("blocked", []) or []:
            if isinstance(entry, dict) and entry.get("reason"):
                ctx.state.setdefault("_rehearsal_reasons", []).append(entry["reason"])


def _short(value: Any, limit: int = 140) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def verdict(persona: Persona, outcome: dict[str, Any]) -> tuple[bool, str]:
    """Did the call land the shape this problem scores? Why not, in one line."""
    actions = outcome["actions"]
    if not actions:
        return False, f"nothing submitted in {outcome['turns']} turns"
    kinds = [a["kind"] for a in actions]
    for banned in persona.forbid_kinds:
        if banned in kinds:
            return False, f"submitted {banned.upper()} beside {kinds}"
    match = next((a for a in actions if a["kind"] == persona.expect_kind), None)
    if match is None:
        return False, f"expected {persona.expect_kind.upper()}, submitted {kinds}"
    for key, want in persona.expect_fields.items():
        # Compare the way the scorer does. ``insurer`` is a free-text enum and
        # folds case, so "Sanitas" is a pass; ``patient_id`` is an exact id and
        # one character out is a failed case.
        norm = FIELD_NORMALIZERS.get(key, normalize.exact_id)
        got = str(match.get(key, ""))
        if norm(got) != norm(want):
            return False, f"{key}={got!r}, expected {want!r}"
    if persona.reason_from_tools:
        seen = outcome["reasons_seen"]
        reason = match.get("reason", "")
        # The reason must at least be a real one: the board compares it exactly
        # against a closed vocabulary, so a plausible-sounding invention fails
        # the case however good the conversation was.
        if reason not in ALL_REASONS:
            return False, f"reason {reason!r} is not in the contract vocabulary"
        if seen and reason not in seen:
            return False, f"reason {reason!r} contradicts the tools, which said {sorted(set(seen))}"
        if not seen:
            # Right answer, wrong route: the model read the provider record and
            # named the rule itself instead of asking check_eligibility. It
            # happens to be correct here; on a subtler rule it would not be.
            return True, (
                f"{persona.expect_kind.upper()}({reason}), but inferred - "
                f"check_eligibility was never called"
            )
        return True, f"{persona.expect_kind.upper()}({reason}), read from the tools"
    detail = ", ".join(f"{k}={match[k]}" for k in sorted(persona.expect_fields))
    return True, f"{persona.expect_kind.upper()} {detail}".strip()


async def rehearse(persona: Persona, settings: Settings, args: Any) -> bool:
    print(f"\n{'=' * 72}\n{persona.key}  {persona.title}\n{'=' * 72}")
    rehearsal = Rehearsal(persona, settings, verbose=args.verbose, max_tokens=args.max_tokens)
    outcome = await rehearsal.run(args.turns)
    if not args.verbose:
        for who, text in rehearsal.transcript:
            print(f"  {who:>7}: {text}")
    print(f"\n  tools:  {' '.join(rehearsal.tool_calls) or '(none)'}")
    for action in outcome["actions"]:
        print(f"  SUBMIT: {json.dumps(action, ensure_ascii=False, default=str)}")
    if not outcome["actions"]:
        print("  SUBMIT: (nothing)")
    ok, why = verdict(persona, outcome)
    print(f"  {'PASS' if ok else 'FAIL'}: {why}  [{outcome['turns']} caller turns]")
    return ok


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="append", choices=sorted(BY_KEY), help="repeatable")
    parser.add_argument("--turns", type=int, default=12, help="caller turns before giving up")
    parser.add_argument("--verbose", action="store_true", help="show tool calls as they happen")
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="override LLM_MAX_TOKENS for this run (see MIN_TOKENS_FOR_A_BOOKING)",
    )
    args = parser.parse_args()

    settings = Settings()
    if not settings.llm_api_key or not settings.llm_base_url:
        print("no LLM endpoint configured: set LLM_PROVIDER and its key in .env", file=sys.stderr)
        return 2
    cap = args.max_tokens or settings.llm_max_tokens
    print(f"model {settings.llm_model} at {settings.llm_base_url}")
    print(
        f"temperature {settings.llm_temperature}, max_tokens {cap}, "
        f"reasoning {settings.llm_reasoning_effort or 'default'}; fake clinic, dry-run submit"
    )
    if cap < MIN_TOKENS_FOR_A_BOOKING:
        print(
            f"WARNING: max_tokens={cap} is below the {MIN_TOKENS_FOR_A_BOOKING} a BOOK "
            f"submit_action measured at, so the booking problems cannot physically be "
            f"submitted. Raise LLM_MAX_TOKENS, or pass --max-tokens to test the prompt alone.",
            file=sys.stderr,
        )

    chosen = [BY_KEY[k] for k in (args.only or sorted(BY_KEY))]
    results = [await rehearse(persona, settings, args) for persona in chosen]
    passed = sum(results)
    print(f"\n{'=' * 72}\n{passed}/{len(results)} rehearsals landed their shape")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
