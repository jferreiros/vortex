"""Best-effort wall-clock bounds for a turn, read off the pipecat frame stream.

``turn.metrics`` wants a ``started_ts``/``ended_ts`` per turn and a TTFB on
agent turns. None of that is an event on the wire, so the pipeline observers
feed this clock the frames they already watch:

- a user speech-start frame opens the caller's turn;
- a decided user-turn end starts the TTFB wait;
- an ``LLMFullResponseStartFrame`` opens the agent's answer;
- each transcription / TTS text frame closes its own turn.

One instance per pipeline - per socket, like everything else on the line.
The clock holds no pipecat type so this module imports no pipecat.
"""

from __future__ import annotations

from datetime import UTC, datetime


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(stamp: datetime) -> str:
    """The same UTC ISO-8601-with-millis shape ``CallLog.event`` writes."""
    return stamp.isoformat(timespec="milliseconds")


class TurnClock:
    """The open turns of one call. Set-once state survives the duplicate
    sightings an observer gets as a frame crosses each pipeline link."""

    def __init__(self) -> None:
        # When the caller's current turn opened. The earliest speech-start
        # sighting wins; a pause mid-turn must not move it forward.
        self.user_open: datetime | None = None
        # When the caller's turn was ruled over: the base the next agent
        # answer's TTFB is measured from. Last sighting wins - the turn-stop
        # decision lands after the VAD's, and the later stamp is the truer one.
        self.reply_wait: datetime | None = None
        # When the current agent answer opened, and when its last spoken chunk
        # ended - the start bound of the next chunk of the same answer.
        self.agent_open: datetime | None = None
        self.agent_last_end: datetime | None = None

    def on_user_speech_start(self) -> None:
        if self.user_open is None:
            self.user_open = _now()

    def on_user_turn_end(self) -> None:
        self.reply_wait = _now()

    def on_agent_response_start(self) -> None:
        self.agent_open = _now()
        self.agent_last_end = None

    def on_agent_response_end(self) -> None:
        self.agent_open = None
        self.agent_last_end = None

    def user_bounds(self) -> tuple[str, str]:
        """(started_ts, ended_ts) for the caller turn that just closed."""
        ended = _now()
        started, self.user_open = self.user_open, None
        return _iso(started or ended), _iso(ended)

    def assistant_bounds(self) -> tuple[str, str, float | None]:
        """(started_ts, ended_ts, ttfb_ms) for one spoken agent chunk.

        TTFB is the wait from the caller's finished turn to the first spoken
        chunk of the answer - the perceived latency, which is the only TTFB a
        listener can hear. Only the first chunk of the answer carries it.
        """
        ended = _now()
        started = self.agent_last_end or self.agent_open or ended
        ttfb_ms: float | None = None
        if self.reply_wait is not None:
            ttfb_ms = round((ended - self.reply_wait).total_seconds() * 1000, 1)
            self.reply_wait = None
        self.agent_last_end = ended
        return _iso(started), _iso(ended), ttfb_ms
