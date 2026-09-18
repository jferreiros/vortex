"""Turn-taking and tool exposure. Consumed by ``line/pipecat_voice.py``.

Owner: the conversation lane.

Interruption handling is entirely ours (the platform does no barge-in). The
VAD decides when the caller starts and stops; ``enable_interruptions`` lets a
caller talk over the agent while it reads options.

TODO(conversation):
- Tune ``vad_stop_secs`` for Spanish speakers and the 8 kHz line; noise
  (problem 12) and 8-second silences (problem 13) both live here.
- Decide whether the model sees every tool at once or a staged subset.
- Add a user-idle prompt ("¿Sigue ahí?") after N seconds of silence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Every tool in vortex/tools.py plus submit_action. Trim to stage the flow.
DEFAULT_EXPOSED_TOOLS: list[str] = [
    "find_patient",
    "validate_national_id",
    "build_registration",
    "resolve_date",
    "find_slots",
    "list_appointments",
    "prepare_booking",
    "prepare_reschedule",
    "prepare_cancel",
    "check_eligibility",
    "triage",
    "nearest_location",
    "find_provider",
    "submit_action",
]


@dataclass(frozen=True)
class TurnSettings:
    enable_interruptions: bool = True
    vad_confidence: float = 0.7
    vad_start_secs: float = 0.2
    vad_stop_secs: float = 0.8
    vad_min_volume: float = 0.6
    # Seconds of caller silence before the agent prompts again. 0 disables.
    user_idle_secs: float = 8.0
    exposed_tools: list[str] = field(default_factory=lambda: list(DEFAULT_EXPOSED_TOOLS))
    # Deepgram language hint. "multi" lets nova-3 switch between languages.
    stt_language: str = "multi"


def default_turn_settings() -> TurnSettings:
    return TurnSettings()
