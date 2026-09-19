"""Offline A/B of VAD+Smart Turn v3.2 vs Soniox endpointing (issue #140)."""

from __future__ import annotations

import pytest

from vortex.conversation.turns import TurnSettings, effective_vad_stop_secs, user_turn_strategies
from vortex.line.smart_turn_ab import (
    id_and_correction_clips,
    run_ab_sync,
    score_soniox_fake,
    vad_mode_settings,
)


def test_vad_mode_settings_match_the_research_knobs() -> None:
    turns = vad_mode_settings()
    assert turns.soniox_turn_detection is False
    assert turns.use_smart_turn is True
    assert turns.smart_turn_stop_secs == 2.0
    assert effective_vad_stop_secs(turns) == 0.2


def test_id_and_correction_clips_cover_the_acceptance_shapes() -> None:
    names = {clip.name for clip in id_and_correction_clips()}
    assert names >= {"id_mid_pause", "correction_mid_pause", "id_long_pause"}
    for clip in id_and_correction_clips():
        assert len(clip.pcm) > 8000  # more than half a second at 8 kHz


def test_soniox_fake_cuts_only_on_pauses_past_the_endpoint_delay() -> None:
    clips = {clip.name: clip for clip in id_and_correction_clips()}
    # 0.8 s mid-pause < 1500 ms delay → no mid-cut.
    short = score_soniox_fake(clips["id_mid_pause"])
    assert short.mid_cuts == 0
    # 1.6 s mid-pause > 1500 ms delay → one mid-cut.
    long = score_soniox_fake(clips["id_long_pause"])
    assert long.mid_cuts == 1


def test_smart_turn_ab_names_a_winner_without_network() -> None:
    pytest.importorskip("pipecat")
    pytest.importorskip("onnxruntime")

    result = run_ab_sync(settings=vad_mode_settings())
    assert set(result.clips) >= {"id_mid_pause", "correction_mid_pause", "id_long_pause"}
    assert result.winner in {"smart_turn", "soniox"}
    assert result.smart_turn_mid_cuts >= 0
    assert result.soniox_mid_cuts >= 0
    # Offline synthetic tones are not real speech: Smart Turn tends to fire
    # COMPLETE on every VAD stop, so Soniox's silence-delay fake usually wins.
    # The gate is that we measured both and kept the lower mid-cut count.
    if result.smart_turn_mid_cuts < result.soniox_mid_cuts:
        assert result.winner == "smart_turn"
    else:
        assert result.winner == "soniox"


def test_vad_mode_strategies_expose_smart_turn_v32() -> None:
    pytest.importorskip("pipecat")
    from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
    from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy

    strategies = user_turn_strategies(vad_mode_settings())
    assert strategies is not None
    stop = strategies.stop[0]
    assert isinstance(stop, TurnAnalyzerUserTurnStopStrategy)
    assert isinstance(stop._turn_analyzer, LocalSmartTurnAnalyzerV3)
    assert stop._turn_analyzer.params.stop_secs == 2.0
    # Default production path stays on Soniox until a live-audio re-run flips it.
    assert TurnSettings().soniox_turn_detection is True
