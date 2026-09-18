"""The model brain: the real receptionist in text mode, plus its cassette.

Text mode is pipecat's fast inner loop: no VAD, no STT, no TTS. The model gets
the lane's system prompt, the lane's exposed tools and the caller's words, and
its tool calls go through the real registry against the fake clinic.

Any OpenAI-compatible endpoint plays. A ``ModelSpec`` (``vortex.models``)
names the endpoint, the key and the request settings the runtime sends, so a
scenario played through ``route("receptionist")`` measures the model the
phone line runs, with the same temperature, token cap and reasoning switch.

Interruptions are simulated the way the voice pipeline would leave the
context: the agent's reply is cut after N words and the caller's next words
follow it. Silence is a bracketed note the model can react to.

A cassette (``evals/conversation/cassettes/<model slug>/<scenario>.json``)
stores every model answer keyed by the exact request. ``replay`` mode answers
from it and never calls the API. A request the cassette does not know means
the prompt, the tools or the script changed since the recording: the scenario
is reported *unverified*, never silently passed.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from evals.bench.pricing import cost_eur
from evals.conversation.brains.base import Trace
from evals.conversation.scenario import CallerTurn, Scenario
from vortex import tools as registry
from vortex.conversation.prompt import GREETING, initial_messages
from vortex.conversation.turns import default_turn_settings
from vortex.models import ModelSpec, resolve, route
from vortex.tools import ToolError

CASSETTES_DIR = Path(__file__).resolve().parent.parent / "cassettes"
DEFAULT_OPENAI_MODEL = os.environ.get("OPENAI_LLM_MODEL", "gpt-4.1-mini")
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


def spec_for(model: str | None) -> ModelSpec:
    """What ``--model`` means for the model brain.

    Empty: the runtime's receptionist route. ``provider/model``: that model.
    A bare name with no slash keeps the old behaviour and means an OpenAI
    model, so ``--brain openai --model gpt-4.1`` still works.
    """
    if not model:
        return route("receptionist")
    if "/" in model:
        return resolve(model)
    return resolve(f"openai/{model}")


def wire_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The message list as the strictest host accepts it.

    Cloudflare Workers AI validates against a schema where ``content`` is a
    string, never a list of parts and never null. OpenAI, Helmcode and the
    Vercel gateway accept both, so every request goes out in the strict
    shape: text parts joined, ``None`` turned into ``""``.
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            content = "\n".join(
                part.get("text", "") if isinstance(part, dict) else str(part) for part in content
            )
        elif content is None:
            content = ""
        out.append({**msg, "content": content})
    return out


class ModelBrain:
    def __init__(
        self,
        *,
        spec: ModelSpec | None = None,
        model: str | None = None,
        replay_only: bool = False,
        record: bool = False,
        openai_only: bool = False,
    ):
        if spec is None:
            spec = (
                resolve(f"openai/{model or DEFAULT_OPENAI_MODEL}")
                if openai_only
                else spec_for(model)
            )
        self.spec = spec
        self.model = spec.model
        self.replay_only = replay_only
        self.record = record
        self.name = "replay" if replay_only else ("openai" if openai_only else "model")
        self._client: Any = None
        self._messages: list[dict[str, Any]] = []
        self._tools: list[dict[str, Any]] = []
        self._cassette: Cassette | None = None
        if not replay_only:
            if not spec.available:
                raise RuntimeError(
                    f"no key for {spec.id}; set the provider's key, or use --brain rules "
                    "or --brain replay"
                )
            self._client = spec.client()

    async def start(self, scenario: Scenario, trace: Trace) -> None:
        trace.model = self.spec.id
        self._messages = list(initial_messages(trace.ctx.now))
        self._messages.append({"role": "assistant", "content": GREETING})
        trace.say("assistant", GREETING)
        exposed = default_turn_settings().exposed_tools
        self._tools = [
            {"type": "function", "function": fn} for fn in registry.function_schemas(exposed)
        ]
        self._cassette = Cassette(CASSETTES_DIR / self.spec.slug / f"{scenario.id}.json")
        if self.replay_only and not self._cassette.entries:
            raise CassetteMiss(
                f"no cassette for {scenario.id} and {self.spec.id}: "
                f"run with --brain model --model {self.spec.id} --record"
            )
        self._cassette.model = self.spec.id

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
                    trace.notes.append(f"{name}: arguments were not valid JSON")
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
        key = Cassette.key(self.spec.id, self._messages, self._tools)
        hit = self._cassette.entries.get(key)
        if hit is not None:
            usage = hit.get("usage", {})
            trace.tokens_in += usage.get("prompt_tokens", 0)
            trace.tokens_out += usage.get("completion_tokens", 0)
            if "ms" in hit:
                trace.llm_ms.append(int(hit["ms"]))
            return hit["message"]
        if self.replay_only:
            raise CassetteMiss(
                "no recorded model answer for this prompt: the system prompt, the tools or "
                "the script changed since the cassette was recorded"
            )
        started = time.monotonic()
        response = await self._client.chat.completions.create(
            messages=wire_messages(self._messages),
            tools=self._tools or None,
            **self.spec.request_kwargs(),
        )
        ms = int((time.monotonic() - started) * 1000)
        choice = response.choices[0]
        message: dict[str, Any] = {"content": choice.message.content}
        if choice.message.tool_calls:
            message["tool_calls"] = [
                {
                    "id": tc.id or f"call_{len(self._messages)}_{i}",
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for i, tc in enumerate(choice.message.tool_calls)
            ]
        if getattr(choice, "finish_reason", None) == "length":
            trace.notes.append(f"reply cut by max_tokens={self.spec.max_tokens}")
        usage = {
            "prompt_tokens": getattr(response.usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(response.usage, "completion_tokens", 0) or 0,
        }
        trace.tokens_in += usage["prompt_tokens"]
        trace.tokens_out += usage["completion_tokens"]
        trace.cost_eur += cost_eur(self.spec.id, usage["prompt_tokens"], usage["completion_tokens"])
        trace.llm_ms.append(ms)
        if self.record:
            self._cassette.entries[key] = {"message": message, "usage": usage, "ms": ms}
            self._cassette.dirty = True
        return message


# The old name. ``--brain openai`` still builds one of these against OpenAI.
OpenAIBrain = ModelBrain
