"""observability/ - what happened on every call, as JSONL, for the live view.

Owner: the observability lane.

Done in the base:
- ``CallLog`` writes one JSON line per event to ``logs/calls.jsonl``.
- ``GET /calls`` on the server returns the recent events grouped by call.

TODO(observability):
- A live view for the jury: tail ``logs/calls.jsonl`` (or ``GET /calls``) and
  render calls in flight, their turns, tool calls and the submitted action.
- A "why did it say that?" view: the tool results that preceded each turn.
- Per-call cost and latency: STT/LLM/TTS timings from pipecat metrics.
"""

from vortex.observability.calllog import CallLog, group_by_call, read_recent

__all__ = ["CallLog", "group_by_call", "read_recent"]
