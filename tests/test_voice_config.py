"""The wall's "Voz del agente" card: the store, the mappings, the directive.

No network — ``fake_store`` stands in for PostgREST, and every mapping is a
pure function over a VoiceConfig.
"""

from __future__ import annotations

import pytest
from nicegui.testing import User

from vortex.line import voice_config


def test_defaults_when_the_table_is_empty(offline_settings, fake_store) -> None:
    cfg = voice_config.load(offline_settings)
    assert cfg == voice_config.VoiceConfig()


def test_defaults_when_there_is_no_store(offline_settings) -> None:
    """A call must sound the same whether or not Supabase is configured."""
    assert voice_config.load(offline_settings) == voice_config.VoiceConfig()


def test_saving_without_a_store_raises_for_the_503(offline_settings) -> None:
    """The card must not report a save that went nowhere."""
    import pytest

    with pytest.raises(RuntimeError, match="no store configured"):
        voice_config.save(offline_settings, {"voice": "male"})


def test_round_trip_persists(offline_settings, fake_store) -> None:
    voice_config.save(offline_settings, {"voice": "male", "tone": 80, "speechRate": 20})
    cfg = voice_config.load(offline_settings)
    assert cfg.voice == "male"
    assert cfg.tone == 80
    assert cfg.speech_rate == 20
    # Unset fields keep the defaults.
    assert cfg.friendliness == 50


def test_partial_save_keeps_stored_fields(offline_settings, fake_store) -> None:
    voice_config.save(offline_settings, {"voice": "male"})
    voice_config.save(offline_settings, {"tone": 90})
    cfg = voice_config.load(offline_settings)
    assert cfg.voice == "male"
    assert cfg.tone == 90


def test_clamps_and_rejects_garbage(offline_settings, fake_store) -> None:
    cfg = voice_config.save(
        offline_settings,
        {"voice": "robot", "tone": 900, "friendliness": -5, "speechRate": "loud"},
    )
    assert cfg.voice == "female"
    assert cfg.tone == 100
    assert cfg.friendliness == 0
    assert cfg.speech_rate == 50


def test_wire_shape_is_camelcase(offline_settings, fake_store) -> None:
    d = voice_config.save(offline_settings, {}).to_dict()
    assert "speechRate" in d and "speech_rate" not in d


def test_preview_merges_over_stored(offline_settings, fake_store) -> None:
    voice_config.save(offline_settings, {"voice": "male", "tone": 10})
    cfg = voice_config.preview_config(offline_settings, {"tone": 70})
    assert cfg.voice == "male"  # stored value survives
    assert cfg.tone == 70  # unsaved slider wins
    # ...and nothing was written.
    assert voice_config.load(offline_settings).tone == 10


def test_speech_rate_mapping() -> None:
    neutral = voice_config.VoiceConfig(speech_rate=50)
    slow = voice_config.VoiceConfig(speech_rate=0)
    fast = voice_config.VoiceConfig(speech_rate=100)
    assert voice_config.elevenlabs_speed(neutral) == 1.0
    assert voice_config.elevenlabs_speed(slow) < 1.0 < voice_config.elevenlabs_speed(fast)
    assert voice_config.elevenlabs_speed(slow) >= 0.7
    assert voice_config.elevenlabs_speed(fast) <= 1.2


def test_apply_gender() -> None:
    """An ElevenLabs voice id is opaque: male is a second id, not a rewrite."""
    assert voice_config.apply_gender("voice-f", "male", "voice-m") == "voice-m"
    assert voice_config.apply_gender("voice-f", "female", "voice-m") == "voice-f"
    # No male id configured: the female voice stands rather than a made-up one.
    assert voice_config.apply_gender("voice-f", "male") == "voice-f"


def test_preview_voice_id_follows_the_card(offline_settings) -> None:
    from vortex.conversation.language import VoicePreset

    female = voice_config.VoiceConfig(voice="female")
    male = voice_config.VoiceConfig(voice="male")
    assert voice_config.preview_voice_id(offline_settings, female) == VoicePreset.ES.female
    assert voice_config.preview_voice_id(offline_settings, male) == VoicePreset.ES.male


def test_synthesize_raises_without_a_key(offline_settings) -> None:
    """The <Say> fallback and the preview 503 both rest on this raising."""
    with pytest.raises(RuntimeError):
        voice_config.synthesize(
            offline_settings,
            voice_config.VoiceConfig(),
            "hola",
            language_code="es",
            voice_name="voice-1",
        )


def test_style_directive() -> None:
    assert voice_config.style_directive(voice_config.VoiceConfig()) == ""
    formal = voice_config.VoiceConfig(tone=10)
    assert "formal" in voice_config.style_directive(formal)
    warm = voice_config.VoiceConfig(friendliness=90)
    assert "warm" in voice_config.style_directive(warm)


# --- the board's own handlers -------------------------------------------------
# ``public.voiceconfig`` is one row both the line and the board read, so the
# board answers the card itself rather than asking the line for it.


async def test_the_board_serves_the_stored_card(user: User, fake_store) -> None:
    voice_config.save(None, {"voice": "male", "tone": 70})

    resp = await user.http_client.get("/api/wall/voice-config")
    assert resp.status_code == 200
    assert resp.json() == {"voice": "male", "tone": 70, "friendliness": 50, "speechRate": 50}


async def test_the_board_saves_the_card(user: User, fake_store) -> None:
    resp = await user.http_client.put("/api/wall/voice-config", json={"speechRate": 20})
    assert resp.status_code == 200
    assert resp.json()["speechRate"] == 20
    assert voice_config.load(None).speech_rate == 20


async def test_the_board_answers_503_with_no_store(user: User, offline_settings) -> None:
    """The card must not report a save that went nowhere."""
    resp = await user.http_client.put("/api/wall/voice-config", json={"voice": "male"})
    assert resp.status_code == 503
    assert resp.json() == {"error": "store_unavailable"}
