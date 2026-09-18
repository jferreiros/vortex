"""observability/ - what happened on every call, as JSONL, for the live view.

Owner: the observability lane.

- ``CallLog`` writes one JSON line per event to ``logs/calls.jsonl``.
- ``GET /calls`` on the server returns the recent events grouped by call.
- ``make board`` serves the live view: ``/`` ops, ``/wall`` jury.
"""

from vortex.observability.calllog import CallLog, group_by_call, read_recent
from vortex.observability.view import CallCard, build_calls

__all__ = ["CallLog", "CallCard", "build_calls", "group_by_call", "read_recent"]
