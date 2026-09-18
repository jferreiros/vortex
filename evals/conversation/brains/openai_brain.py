"""The model brain: the real receptionist in text mode, plus its cassette.

Text mode is pipecat's fast inner loop: no VAD, no STT, no TTS. The model gets
the lane's system prompt, the lane's exposed tools and the caller's words, and
its tool calls go through the real registry against the fake clinic.

Interruptions are simulated the way the voice pipeline would leave the
context: the agent's reply is cut after N words and the caller's next words
follow it. Silence is a bracketed note the model can react to.

A cassette (``evals/conversation/cassettes/<scenario>.json``) stores every
model answer keyed by the exact request. ``replay`` mode answers from it and
never calls the API. A request the cassette does not know means the prompt,
the tools or the script changed since the recording: the scenario is reported
*unverified*, never silently passed.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import yaml

from evals.conversation.brains.base import Trace
from evals.conversation.scenario import CallerTurn, Scenario
from vortex import tools as registry
from vortex.conversation.prompt import GREETING, initial_messages
from vortex.conversation.turns import default_turn_settings
from vortex.tools import ToolError

CASSETTES_DIR = Path(__file__).resolve().parent.parent / "cassettes"
PRICING = Path(__file__).resolve().parent.parent.parent / "voice" / "pricing.yaml"
DEFAULT_MODEL = os.environ.get("OPENAI_LLM_MODEL", "gpt-4.1-mini")
MAX_TOOL_ROUNDS = 8  # per caller turn; the model must speak eventually


class CassetteMiss(RuntimeError):
    pass


class Cassette:
    def __init__(self, path: Path):
        self.path = path
        self.entries: dict[str, Any] = {}
        self.model = ""
        self.dirty = False
        if path.exists():
            data = json.loads(path.read_text())
            self.entries = data.get("entries", {})
            self.model = data.get("model", "")

    @staticmethod
    def key(model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> str:
        blob = json.dumps({"m": model, "msgs": messages, "tools": tools}, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:24]

    def save(self) -> None:
        if not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"model": self.model, "entries": self.entries}, indent=1, ensure_ascii=False)
        )


def _llm_prices() -> dict[str, dict[str, float]]:
    try:
        doc = yaml.safe_load(PRICING.read_text())
    except OSError:
        return {}
    return {k: v for k, v in (doc.get("llm") or {}).items()}


def cost_eur(model: str, tokens_in: int, tokens_out: int) -> float:
    prices = _llm_prices()
    row = prices.get(model)
    if not row or "usd_per_1m_input" not in row:
        return 0.0
    eur = float(yaml.safe_load(PRICING.read_text()).get("eur_per_usd", 0.92))
    usd = tokens_in / 1e6 * row["usd_per_1m_input"] + tokens_out / 1e6 * row["usd_per_1m_output"]
    return usd * eur


class OpenAIBrain:
    def __init__(
        self, *, model: str | None = None, replay_only: bool = False, record: bool = False
    ):
        self.model = model or DEFAULT_MODEL
        self.replay_only = replay_only
        self.record = record
        self.name = "replay" if replay_only else "openai"
        self._client: Any = None
        self._messages: list[dict[str, Any]] = []
        self._tools: list[dict[str, Any]] = []
        self._cassette: Cassette | None = None
        if not replay_only:
            if not os.environ.get("OPENAI_API_KEY"):
                raise RuntimeError("OPENAI_API_KEY is not set; use --brain rules or --brain replay")
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI()

    async def start(self, scenario: Scenario, trace: Trace) -> None:
        self._messages = list(initial_messages(trace.ctx.now))
        self._messages.append({"role": "assistant", "content": GREETING})
        trace.say("assistant", GREETING)
        exposed = default_turn_settings().exposed_tools
        self._tools = [
            {"type": "function", "function": fn} for fn in registry.function_schemas(exposed)
        ]
        self._cassette = Cassette(CASSETTES_DIR / f"{scenario.id}.json")
        if self.replay_only and not self._cassette.entries:
            raise CassetteMiss(f"no cassette for {scenario.id}: run with --brain openai --record")
        if self.replay_only:
            self.model = self._cassette.model or self.model
        else:
            self._cassette.model = self.model

    async def hear(self, turn: CallerTurn, trace: Trace) -> str:
        if (
            turn.interrupt_after_words
            and self._messages
            and self._messages[-1]["role"] == "assistant"
        ):
            last = self._messages[-1]
            words = (last.get("content") or "").split()
            cut = " ".join(words[: turn.interrupt_after_words])
            last["content"] = cut + " —"
            trace.transcript[-1] = ("assistant", cut + " — [interrupted]")
        if turn.silence_secs and not turn.says:
            self._messages.append(
                {
                    "role": "user",
                    "content": f"[the caller has been silent for {turn.silence_secs:.0f} seconds]",
                }
            )
        else:
            self._messages.append({"role": "user", "content": turn.says})
            trace.say("user", turn.says)
        reply = ""
        for _ in range(MAX_TOOL_ROUNDS):
            answer = await self._complete(trace)
            calls = answer.get("tool_calls") or []
            content = answer.get("content") or ""
            self._messages.append(
                {
                    "role": "assistant",
                    "content": content or None,
                    **({"tool_calls": calls} if calls else {}),
                }
            )
            if content:
                reply = (reply + " " + content).strip()
            if not calls:
                break
            for call in calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                try:
                    result = await trace.call(name, args)
                    payload = json.dumps(result, ensure_ascii=False)
                except ToolError as exc:
                    payload = json.dumps({"error": str(exc)})
                except Exception as exc:  # the model must hear about failures
                    payload = json.dumps({"error": f"{type(exc).__name__}: {exc}"})
                self._messages.append(
                    {"role": "tool", "tool_call_id": call["id"], "content": payload}
                )
        if reply:
            trace.say("assistant", reply)
        return reply

    async def hangup(self, trace: Trace) -> None:
        if self._cassette:
            self._cassette.save()

    async def _complete(self, trace: Trace) -> dict[str, Any]:
        assert self._cassette is not None
        key = Cassette.key(self.model, self._messages, self._tools)
        hit = self._cassette.entries.get(key)
        if hit is not None:
            trace.tokens_in += hit.get("usage", {}).get("prompt_tokens", 0)
            trace.tokens_out += hit.get("usage", {}).get("completion_tokens", 0)
            return hit["message"]
        if self.replay_only:
            raise CassetteMiss(
                "no recorded model answer for this prompt: the system prompt, the tools or "
                "the script changed since the cassette was recorded"
            )
        started = time.monotonic()
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=self._messages,
            tools=self._tools or None,
            temperature=0,
            seed=7,
        )
        choice = response.choices[0].message
        message: dict[str, Any] = {"content": choice.content}
        if choice.tool_calls:
            message["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in choice.tool_calls
            ]
        usage = {
            "prompt_tokens": getattr(response.usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(response.usage, "completion_tokens", 0) or 0,
        }
        trace.tokens_in += usage["prompt_tokens"]
        trace.tokens_out += usage["completion_tokens"]
        trace.cost_eur += cost_eur(self.model, usage["prompt_tokens"], usage["completion_tokens"])
        trace.notes.append(f"llm round trip {int((time.monotonic() - started) * 1000)} ms")
        if self.record:
            self._cassette.entries[key] = {"message": message, "usage": usage}
            self._cassette.dirty = True
        return message
