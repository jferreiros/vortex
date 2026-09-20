"""Office/typing beds on the output mixer, and the lookup switcher."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from vortex.line.ambience import (
    OFFICE_SOUND,
    SOUNDS_DIR,
    _make_ambience_mixer,
    _wav_is_transport_ready,
)


def test_sound_files_are_8khz_mono_int16_and_small() -> None:
    for name in ("office.wav", "typing.wav"):
        path = SOUNDS_DIR / name
        assert path.is_file()
        assert path.stat().st_size < 150_000
        assert _wav_is_transport_ready(path)
        with wave.open(str(path), "rb") as handle:
            seconds = handle.getnframes() / handle.getframerate()
            assert 4.0 < seconds < 9.0


def test_mixer_is_a_pipecat_mixer() -> None:
    pytest.importorskip("pipecat")
    from pipecat.audio.mixers.base_audio_mixer import BaseAudioMixer
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams

    mixer = _make_ambience_mixer()
    assert mixer is not None
    assert isinstance(mixer, BaseAudioMixer)
    assert OFFICE_SOUND in mixer._sound_files
    FastAPIWebsocketParams(audio_out_enabled=True, audio_out_mixer=mixer)


def test_mixer_skips_missing_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vortex.line import ambience as ambience_module

    monkeypatch.setattr(ambience_module, "SOUNDS_DIR", tmp_path)
    assert _make_ambience_mixer() is None


async def test_office_mix_is_not_silence() -> None:
    pytest.importorskip("pipecat")
    import numpy as np

    mixer = _make_ambience_mixer()
    assert mixer is not None
    await mixer.start(8000)
    silence = b"\x00" * 640
    mixed = np.frombuffer(await mixer.mix(silence), dtype=np.int16)
    assert int(np.max(np.abs(mixed))) > 200


async def test_office_loop_stays_up_across_the_wrap() -> None:
    pytest.importorskip("pipecat")
    import numpy as np
    import soundfile as sf

    from vortex.line.ambience import SOUNDS_DIR

    x, sr = sf.read(str(SOUNDS_DIR / "office.wav"), dtype="float64")
    hop = int(0.05 * sr)
    rms = np.array(
        [float(np.sqrt(np.mean(x[i : i + hop] ** 2))) for i in range(0, len(x) - hop, hop)]
    )
    med = float(np.median(rms))
    # No silent hole, including the last 200 ms before the file repeats.
    assert float(np.min(rms)) > med / (10 ** (8 / 20))
    wrap = np.concatenate([x[-hop:], x[:hop]])
    assert float(np.sqrt(np.mean(wrap**2))) > med / (10 ** (6 / 20))


async def test_switcher_types_on_tools_and_office_on_answer() -> None:
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import (
        FunctionCallInProgressFrame,
        FunctionCallResultFrame,
        LLMFullResponseStartFrame,
        MixerUpdateSettingsFrame,
        TextFrame,
    )
    from pipecat.processors.frame_processor import FrameDirection

    from vortex.line.pipecat_voice import _AmbienceSwitcher

    events: list[tuple[str, dict]] = []

    class Log:
        def event(self, kind: str, **kwargs: object) -> None:
            events.append((kind, kwargs))

    class Session:
        ctx = type("Ctx", (), {"log": Log()})()

    switcher = _AmbienceSwitcher(Session())  # type: ignore[arg-type]
    pushed: list[object] = []

    async def capture(frame: object, direction: object = FrameDirection.DOWNSTREAM) -> None:
        pushed.append(frame)

    switcher.push_frame = capture  # type: ignore[method-assign]

    await switcher.process_frame(TextFrame("hola"), FrameDirection.DOWNSTREAM)
    await switcher.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
    assert not any(isinstance(frame, MixerUpdateSettingsFrame) for frame in pushed)

    await switcher.process_frame(
        FunctionCallInProgressFrame(function_name="find_patient", tool_call_id="c1", arguments={}),
        FrameDirection.DOWNSTREAM,
    )
    typing = [frame for frame in pushed if isinstance(frame, MixerUpdateSettingsFrame)]
    assert typing and typing[-1].settings["sound"] == "typing"
    assert events[-1] == ("voice.ambience", {"sound": "typing"})

    await switcher.process_frame(
        FunctionCallResultFrame(
            function_name="find_patient", tool_call_id="c1", arguments={}, result={}
        ),
        FrameDirection.DOWNSTREAM,
    )
    assert [e for e, _ in events] == ["voice.ambience"]

    await switcher.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
    office = [frame for frame in pushed if isinstance(frame, MixerUpdateSettingsFrame)]
    assert office[-1].settings["sound"] == "office"
    assert events[-1] == ("voice.ambience", {"sound": "office"})
