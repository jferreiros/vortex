"""The receptionists a scenario can be played against."""

from __future__ import annotations

import os

from evals.conversation.brains.base import Brain, ToolCall, Trace


def pick_brain(name: str) -> str:
    """Resolve ``auto`` to a concrete brain name.

    ``auto`` stays offline unless ``OPENAI_API_KEY`` is set, so ``make evals``
    never spends a key by surprise. ``model`` is the explicit way to play the
    runtime's model (or any ``provider/model`` with ``--model``).
    """
    if name != "auto":
        return name
    return "openai" if os.environ.get("OPENAI_API_KEY") else "rules"


def make_brain(name: str, **kwargs) -> Brain:
    if name == "rules":
        from evals.conversation.brains.rules import RulesBrain

        return RulesBrain()
    if name == "openai":
        from evals.conversation.brains.openai_brain import ModelBrain

        return ModelBrain(openai_only=True, **kwargs)
    if name in ("model", "replay"):
        from evals.conversation.brains.openai_brain import ModelBrain

        return ModelBrain(replay_only=(name == "replay"), **kwargs)
    raise ValueError(f"unknown brain {name!r}")


__all__ = ["Brain", "ToolCall", "Trace", "make_brain", "pick_brain"]
