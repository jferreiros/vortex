"""What a brain is: something that hears the caller and calls tools.

The runner owns the ``Trace``: every tool call goes through ``Trace.call`` so
the trajectory and the submissions are recorded the same way for every brain.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel

from evals.conversation.scenario import CallerTurn, Scenario
from vortex import tools as registry
from vortex.contract import ToolContext
from vortex.tools import ToolError


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    ms: int


@dataclass
class Trace:
    ctx: ToolContext
    calls: list[ToolCall] = field(default_factory=list)
    transcript: list[tuple[str, str]] = field(default_factory=list)  # (role, text)
    cost_eur: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    notes: list[str] = field(default_factory=list)
    # One entry per model round trip, milliseconds. Empty for the rules brain.
    llm_ms: list[int] = field(default_factory=list)
    # The model id (``provider/model``) that produced the answers, if any.
    model: str = ""

    async def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Run one tool through the registry and record it. Errors are recorded and re-raised."""
        started = time.monotonic()
        try:
            result: BaseModel = await registry.call_tool(name, self.ctx, args)
        except ToolError as exc:
            self.calls.append(
                ToolCall(name, args, None, str(exc), int((time.monotonic() - started) * 1000))
            )
            raise
        except Exception as exc:
            self.calls.append(
                ToolCall(
                    name,
                    args,
                    None,
                    f"{type(exc).__name__}: {exc}",
                    int((time.monotonic() - started) * 1000),
                )
            )
            raise
        data = result.model_dump(mode="json")
        self.calls.append(
            ToolCall(name, args, data, None, int((time.monotonic() - started) * 1000))
        )
        return data

    def say(self, role: str, text: str) -> None:
        self.transcript.append((role, text))
        if role == "assistant":
            self.ctx.log.assistant_turn(text)
        elif role == "user":
            self.ctx.log.user_turn(text)

    @property
    def trajectory(self) -> list[str]:
        return [c.name for c in self.calls]


class Brain(Protocol):
    name: str

    async def start(self, scenario: Scenario, trace: Trace) -> None:
        """A fresh conversation. Speak the greeting."""

    async def hear(self, turn: CallerTurn, trace: Trace) -> str:
        """The caller spoke. Call tools as needed and return what the agent says back."""

    async def hangup(self, trace: Trace) -> None:
        """The caller hung up. Last chance to submit."""
