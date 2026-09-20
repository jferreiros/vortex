"""observability/ - what happened on every call, in Postgres, for the live view.

Owner: the observability lane.

- ``CallLog`` writes one row per event to ``public.call_events``.
- ``GET /calls`` on the server returns those events grouped by call.
- ``make board`` serves the live view: ``/`` ops, ``/wall`` jury.
"""

from vortex.observability.calllog import CallLog, group_by_call
from vortex.observability.view import CallCard, build_calls

__all__ = ["CallCard", "CallLog", "build_calls", "group_by_call"]
