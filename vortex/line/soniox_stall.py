"""Finalize a user turn the Soniox endpointer can no longer finish.

Soniox's endpointer emits ``<end>`` only while audio flows: the tokens of an
utterance stay unfinalized until it hears what follows them. Twilio Media
Streams never starves - the platform streams room tone between words - but a
caller whose upstream stops sending audio does starve it, and the evidence run
of 2026-09-19 (``/home/factory/voicecall.py``, call CA-voicetest-1789811079)
lost every turn that way: the transcript sat unflushed for ~30 s, the turn
never closed, and the agent never answered. Streaming silence between
utterances is what keeps a *synthetic* caller alive; this guard is what keeps
the line alive when the audio stops anyway.

The guard watches the inbound stream. While a turn is open and no audio has
arrived for ``STALL_FINALIZE_SECS`` - a live line always carries frames, so
only a stalled stream gets here - it sends Soniox the same ``finalize``
message the service sends on a VAD stop in pipecat's own turn-detection mode.
Soniox flushes the final transcript and the turn closes normally. If Soniox
does not answer at all, the last interim text it streamed is promoted to the
final transcript, so the words the caller said are never dropped on the floor.

Owner: the line lane.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

# Finalize a turn once the inbound stream has been this quiet. A live Twilio
# line delivers a frame every 20 ms; only a caller (or network) that stopped
# sending audio entirely is quiet for half a second.
STALL_FINALIZE_SECS = 0.5

# How long a finalize request may stay unanswered before the last interim text
# is promoted to the final transcript.
FALLBACK_FINALIZE_SECS = 1.5

# How often the watcher wakes up. Half the stall threshold, so a stall is
# acted on within a quarter second of becoming due.
WATCHER_TICK_SECS = STALL_FINALIZE_SECS / 2


def make_stall_guarded_soniox_stt(
    *,
    stall_finalize_secs: float = STALL_FINALIZE_SECS,
    fallback_finalize_secs: float = FALLBACK_FINALIZE_SECS,
    on_event: Callable[..., None] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> type:
    """Build the guarded ``SonioxSTTService`` class.

    pipecat is imported here, not at module scope, so the server starts and the
    smoke test runs without it. ``on_event`` receives (kind, **fields) lines for
    the call log; ``clock`` is injectable for tests.
    """
    from pipecat.frames.frames import (
        InterimTranscriptionFrame,
        ProposedUserStoppedSpeakingFrame,
        TranscriptionFrame,
    )
    from pipecat.processors.frame_processor import FrameDirection
    from pipecat.services.soniox.stt import FINALIZE_MESSAGE, SonioxSTTService
    from pipecat.utils.time import time_now_iso8601
    from websockets.protocol import State

    class StallGuardedSonioxSTT(SonioxSTTService):
        """Soniox STT that never leaves a spoken turn hanging open."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._stall_finalize_secs = stall_finalize_secs
            self._fallback_finalize_secs = fallback_finalize_secs
            self._on_event = on_event
            self._clock = clock
            # Last time inbound audio arrived. ``None`` until the first frame.
            self._last_audio_at: float | None = None
            # One stall episode per starvation: armed by new audio or a new turn.
            self._stall_handled = True
            # The newest interim text, for the promote-to-final fallback.
            self._last_interim_text = ""
            self._synthesized_final = False

        # -- wiring ------------------------------------------------------------

        async def setup(self, setup: Any) -> None:
            await super().setup(setup)
            self.create_task(self._stall_watcher(), f"{self}::stall_watcher")

        async def run_stt(self, audio: bytes):
            self.note_audio()
            async for frame in super().run_stt(audio):
                yield frame

        async def _user_turn_started(self) -> None:
            self._stall_handled = False
            self._last_interim_text = ""
            self._synthesized_final = False
            await super()._user_turn_started()

        async def _user_turn_stopped(self) -> None:
            self._last_interim_text = ""
            await super()._user_turn_stopped()

        async def push_frame(self, frame: Any, direction: Any = FrameDirection.DOWNSTREAM) -> None:
            if isinstance(frame, InterimTranscriptionFrame):
                self.note_interim(frame.text)
            elif isinstance(frame, TranscriptionFrame):
                self.note_final()
            await super().push_frame(frame, direction)

        # -- probe surface (tests drive these directly) -------------------------

        def note_audio(self) -> None:
            """A frame of inbound audio arrived. Re-arms the stall episode."""
            self._last_audio_at = self._clock()
            self._stall_handled = False
            self._synthesized_final = False

        def note_interim(self, text: str | None) -> None:
            """An interim transcript arrived: remember it for the fallback."""
            stripped = (text or "").strip()
            if stripped:
                self._last_interim_text = stripped

        def note_final(self) -> None:
            """The real final transcript arrived: the fallback is not needed."""
            self._last_interim_text = ""

        def stall_due(self, now: float | None = None) -> bool:
            """Should this tick send a finalize?

            Only while a turn is open (Soniox turn-detection mode; in pipecat
            mode the VAD stop finalizes and this stays idle), with audio behind
            it, quiet for ``stall_finalize_secs``, and no episode in flight.
            """
            if self._stall_handled or not self._user_turn_open:
                return False
            if self._last_audio_at is None:
                return False
            moment = self._clock() if now is None else now
            return moment - self._last_audio_at >= self._stall_finalize_secs

        async def request_finalize(self) -> None:
            """Ask Soniox to flush the open turn, then fall back if it will not."""
            self._stall_handled = True
            moment = self._clock()
            silence = (
                round(moment - self._last_audio_at, 3) if self._last_audio_at is not None else None
            )
            self._emit("voice.stt_stall_finalize", silence_secs=silence)
            await self._send_finalize()
            deadline = self._clock() + self._fallback_finalize_secs
            while self._clock() < deadline and self._user_turn_open:
                await asyncio.sleep(0.05)
            if not self._user_turn_open:
                return
            text = self._last_interim_text
            if not text or self._synthesized_final:
                return
            self._synthesized_final = True
            # Cleared before the push, so a later real final for the same
            # words cannot re-arm the fallback.
            self.note_final()
            self._emit("voice.stt_stall_fallback", text=text)
            await self.push_frame(
                TranscriptionFrame(
                    text=text, user_id="", timestamp=time_now_iso8601(), finalized=True
                )
            )
            await self.push_frame(ProposedUserStoppedSpeakingFrame())

        # -- internals ----------------------------------------------------------

        async def _stall_watcher(self) -> None:
            while True:
                await asyncio.sleep(WATCHER_TICK_SECS)
                try:
                    if self.stall_due():
                        await self.request_finalize()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # a guard must never take the call down
                    log.warning(f"{self}: stall watcher failed: {exc}")

        async def _send_finalize(self) -> None:
            ws = self._websocket
            if not ws or ws.state is not State.OPEN:
                return
            try:
                await ws.send(FINALIZE_MESSAGE)
            except Exception as exc:
                log.warning(f"{self}: finalize send failed: {exc}")

        def _emit(self, kind: str, **fields: Any) -> None:
            if self._on_event is not None:
                try:
                    self._on_event(kind, **fields)
                except Exception:  # logging must never break the guard
                    log.exception(f"{self}: event callback failed")

    return StallGuardedSonioxSTT
