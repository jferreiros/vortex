"""Vortex evaluation harness.

Three layers, runnable on their own:

- ``evals.logic``         tool-level cases, no voice, no model. Seconds. Every PR.
- ``evals.conversation``  scripted callers driving the agent as text. Every PR.
- ``evals.voice``         provider benchmark: latency, WER, cost. Manual; spends money.

``python -m evals`` is the entry point. ``docs/evals.md`` is the manual.
"""
