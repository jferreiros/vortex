"""Turn-taking and tool exposure. Consumed by ``line/pipecat_voice.py``.

Owner: the conversation lane.

Interruption handling is entirely ours (the platform does no barge-in). The
VAD decides when the caller starts and stops; ``enable_interruptions`` lets a
caller talk over the agent while it reads options.

TODO(conversation):
- Tune ``vad_stop_secs`` and the Soniox endpoint knobs for Spanish speakers
  and the 8 kHz line; noise
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
    # Noisy-caller settings (problem 12): a higher bar before Silero calls it
    # speech, so a bus going past does not become a barge-in. Smart-turn v3
    # (loaded by the user aggregator) then rejects non-turns Silero lets
    # through. No denoiser in front of STT: Deepgram/AssemblyAI both document
    # worse WER after suppression, and Soniox v5 is trained for telephony noise.
    vad_confidence: float = 0.85
    vad_start_secs: float = 0.3
    vad_stop_secs: float = 0.4
    vad_min_volume: float = 0.7
    # Seconds of caller silence before the agent prompts again. 0 disables.
    user_idle_secs: float = 8.0
    exposed_tools: list[str] = field(default_factory=lambda: list(DEFAULT_EXPOSED_TOOLS))

    # --- Soniox STT ---------------------------------------------------------
    # Hints, not a lock: stt-rt-v5 still transcribes anything it hears, and with
    # language identification on it tags every token with the language it heard.
    stt_language_hints: tuple[str, ...] = ("es", "ca")
    # True  -> Soniox's own endpoint detection ends the turn (vad_force_turn_endpoint=False)
    # False -> pipecat's VAD ends the turn and finalises Soniox
    soniox_turn_detection: bool = True
    # The three below only bite when soniox_turn_detection is True.
    # 1500 ms tolerates the pause callers make mid-DNI ("doce, treinta y cuatro...").
    stt_max_endpoint_delay_ms: int = 1500
    stt_endpoint_sensitivity: float = 0.3
    stt_endpoint_latency_adjustment_level: int = 2


def default_turn_settings() -> TurnSettings:
    return TurnSettings()
