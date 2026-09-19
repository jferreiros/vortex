"""Offline A/B: VAD + Smart Turn v3.2 vs Soniox endpointing on ID/correction clips.

No Soniox API key and no network. Smart Turn runs the bundled ONNX model on
synthetic 8 kHz PCM. Soniox is a silence-delay fake keyed on
``TurnSettings.stt_max_endpoint_delay_ms`` — the acoustic fallback of their
endpointer, not the semantic ``<end>`` token.

Winner = fewer mid-utterance turn cuts. The production default stays Soniox
until a live-audio re-run says otherwise; this module is the offline gate the
research doc asked for (docs/research/03-turn-detection.md step 5).

Owner: the line lane.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from vortex.conversation.turns import TurnSettings, default_turn_settings, effective_vad_stop_secs

SAMPLE_RATE = 8000
FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
ENERGY_SPEECH_FLOOR = 500
# A cut more than this many ms before the last speech sample is "mid-turn".
MID_CUT_SLACK_MS = 200

ModeName = Literal["smart_turn", "soniox"]


@dataclass(frozen=True)
class TurnClip:
    """One ID or correction utterance with a known mid-pause."""

    name: str
    pcm: bytes  # 16-bit mono PCM at SAMPLE_RATE
    # Milliseconds from start where a cut is still mid-utterance (before the
    # final speech burst ends). Derived from energy if left None.
    last_speech_ms: float | None = None


@dataclass(frozen=True)
class ModeScore:
    mode: ModeName
    mid_cuts: int
    cuts_ms: tuple[float, ...]


@dataclass(frozen=True)
class AbResult:
    clips: tuple[str, ...]
    smart_turn: ModeScore
    soniox: ModeScore
    winner: ModeName

    @property
    def smart_turn_mid_cuts(self) -> int:
        return self.smart_turn.mid_cuts

    @property
    def soniox_mid_cuts(self) -> int:
        return self.soniox.mid_cuts


def _tone(secs: float, *, freq: float = 180.0, amp: float = 0.3, seed: int = 0) -> bytes:
    """Speech-shaped burst: f0 + harmonics under a syllable envelope."""
    n = max(1, int(secs * SAMPLE_RATE))
    t = np.arange(n) / SAMPLE_RATE
    rng = np.random.default_rng(seed)
    f0 = freq + 8.0 * rng.random()
    voice = amp * (
        np.sin(2 * np.pi * f0 * t)
        + 0.45 * np.sin(2 * np.pi * 2 * f0 * t)
        + 0.2 * np.sin(2 * np.pi * 3 * f0 * t)
    )
    env = 0.55 * (1.0 + np.sin(2 * np.pi * 4.2 * t + rng.random()))
    return (np.clip(voice * env, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()


def _silence(secs: float) -> bytes:
    return b"\x00\x00" * max(0, int(secs * SAMPLE_RATE))


def id_and_correction_clips() -> tuple[TurnClip, ...]:
    """The two clip families the acceptance criterion names.

    Mid-pauses mirror a DNI read with a breath in the middle, and a correction
    ("el martes… no, el miércoles"). A third long-pause clip stresses the
    Soniox 1500 ms delay against Smart Turn's 2.0 s silence fallback.
    """
    id_clip = (
        _tone(1.0, freq=175, seed=1) + _silence(0.8) + _tone(1.0, freq=195, seed=2) + _silence(0.5)
    )
    correction = (
        _tone(0.8, freq=160, seed=3) + _silence(0.5) + _tone(1.0, freq=190, seed=4) + _silence(0.5)
    )
    long_pause = (
        _tone(0.8, freq=170, seed=5) + _silence(1.6) + _tone(0.8, freq=205, seed=6) + _silence(0.5)
    )
    return (
        TurnClip(name="id_mid_pause", pcm=id_clip),
        TurnClip(name="correction_mid_pause", pcm=correction),
        TurnClip(name="id_long_pause", pcm=long_pause),
    )


def _last_speech_ms(pcm: bytes) -> float:
    samples = np.frombuffer(pcm, dtype=np.int16)
    nonzero = np.where(np.abs(samples) > ENERGY_SPEECH_FLOOR)[0]
    if len(nonzero) == 0:
        return 0.0
    return float(nonzero[-1]) / SAMPLE_RATE * 1000.0


def _frames(pcm: bytes) -> list[tuple[bytes, bool]]:
    """Split PCM into 20 ms frames tagged by a simple energy VAD."""
    frame_bytes = FRAME_SAMPLES * 2
    out: list[tuple[bytes, bool]] = []
    for offset in range(0, len(pcm), frame_bytes):
        chunk = pcm[offset : offset + frame_bytes]
        if len(chunk) < frame_bytes:
            chunk = chunk + b"\x00" * (frame_bytes - len(chunk))
        energy = float(np.mean(np.abs(np.frombuffer(chunk, dtype=np.int16))))
        out.append((chunk, energy > ENERGY_SPEECH_FLOOR))
    return out


def score_soniox_fake(clip: TurnClip, settings: TurnSettings | None = None) -> ModeScore:
    """Silence-delay stand-in for Soniox endpointing. No network."""
    turns = settings or default_turn_settings()
    delay_ms = float(turns.stt_max_endpoint_delay_ms)
    last_ms = clip.last_speech_ms if clip.last_speech_ms is not None else _last_speech_ms(clip.pcm)
    speaking = False
    silence_ms = 0.0
    t_ms = 0.0
    cuts: list[float] = []
    for _chunk, is_speech in _frames(clip.pcm):
        if is_speech:
            speaking = True
            silence_ms = 0.0
        elif speaking:
            silence_ms += FRAME_MS
            if silence_ms >= delay_ms:
                cuts.append(t_ms)
                speaking = False
                silence_ms = 0.0
        t_ms += FRAME_MS
    mid = sum(1 for cut in cuts if cut < last_ms - MID_CUT_SLACK_MS)
    return ModeScore(mode="soniox", mid_cuts=mid, cuts_ms=tuple(cuts))


async def score_smart_turn(clip: TurnClip, settings: TurnSettings | None = None) -> ModeScore:
    """Run the bundled LocalSmartTurnAnalyzerV3 over the clip."""
    turns = settings or default_turn_settings()
    from pipecat.audio.turn.base_turn_analyzer import EndOfTurnState
    from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
    from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3

    vad_stop_ms = effective_vad_stop_secs(turns) * 1000.0
    analyzer = LocalSmartTurnAnalyzerV3(
        cpu_count=1,
        sample_rate=SAMPLE_RATE,
        params=SmartTurnParams(stop_secs=turns.smart_turn_stop_secs),
    )
    analyzer.set_sample_rate(SAMPLE_RATE)

    last_ms = clip.last_speech_ms if clip.last_speech_ms is not None else _last_speech_ms(clip.pcm)
    speaking = False
    silence_ms = 0.0
    t_ms = 0.0
    cuts: list[float] = []
    for chunk, is_speech in _frames(clip.pcm):
        if is_speech:
            speaking = True
            silence_ms = 0.0
        elif speaking:
            silence_ms += FRAME_MS
        state = analyzer.append_audio(chunk, is_speech)
        fired = False
        # Mirror TurnAnalyzerUserTurnStopStrategy: on VAD stop, ask the model.
        if (
            speaking
            and not is_speech
            and silence_ms + 1e-6 >= vad_stop_ms
            and silence_ms - FRAME_MS < vad_stop_ms
        ):
            state_ml, _metrics = await analyzer.analyze_end_of_turn()
            if state_ml == EndOfTurnState.COMPLETE:
                cuts.append(t_ms)
                speaking = False
                silence_ms = 0.0
                fired = True
        if not fired and state == EndOfTurnState.COMPLETE:
            cuts.append(t_ms)
            speaking = False
            silence_ms = 0.0
        t_ms += FRAME_MS
    mid = sum(1 for cut in cuts if cut < last_ms - MID_CUT_SLACK_MS)
    return ModeScore(mode="smart_turn", mid_cuts=mid, cuts_ms=tuple(cuts))


def _pick_winner(smart: ModeScore, soniox: ModeScore) -> ModeName:
    if smart.mid_cuts < soniox.mid_cuts:
        return "smart_turn"
    if soniox.mid_cuts < smart.mid_cuts:
        return "soniox"
    # Tie: keep Soniox — it is the live default and needs no ONNX load.
    return "soniox"


async def run_ab(
    clips: tuple[TurnClip, ...] | None = None,
    settings: TurnSettings | None = None,
) -> AbResult:
    """Score both modes on the ID/correction clips and name a winner."""
    turns = settings or default_turn_settings()
    bundle = clips or id_and_correction_clips()
    smart_total = 0
    soniox_total = 0
    smart_cuts: list[float] = []
    soniox_cuts: list[float] = []
    names: list[str] = []
    for clip in bundle:
        names.append(clip.name)
        smart = await score_smart_turn(clip, turns)
        soniox = score_soniox_fake(clip, turns)
        smart_total += smart.mid_cuts
        soniox_total += soniox.mid_cuts
        smart_cuts.extend(smart.cuts_ms)
        soniox_cuts.extend(soniox.cuts_ms)
    smart_score = ModeScore(mode="smart_turn", mid_cuts=smart_total, cuts_ms=tuple(smart_cuts))
    soniox_score = ModeScore(mode="soniox", mid_cuts=soniox_total, cuts_ms=tuple(soniox_cuts))
    return AbResult(
        clips=tuple(names),
        smart_turn=smart_score,
        soniox=soniox_score,
        winner=_pick_winner(smart_score, soniox_score),
    )


def run_ab_sync(
    clips: tuple[TurnClip, ...] | None = None,
    settings: TurnSettings | None = None,
) -> AbResult:
    """Sync wrapper for tests and scripts."""
    return asyncio.run(run_ab(clips=clips, settings=settings))


def vad_mode_settings(**overrides: Any) -> TurnSettings:
    """``soniox_turn_detection=False`` with the Smart Turn knobs from the research."""
    base = dict(
        soniox_turn_detection=False,
        use_smart_turn=True,
        smart_turn_stop_secs=2.0,
        smart_turn_vad_stop_secs=0.2,
        vad_confidence=0.8,
        vad_start_secs=0.3,
        vad_min_volume=0.6,
    )
    base.update(overrides)
    return TurnSettings(**base)
