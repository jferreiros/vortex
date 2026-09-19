"""The wall's "Voz del agente" card: sqlite store, mappings, prompt directive.

No network — the store is a file under the same tmp dir as the test call log,
and every mapping is a pure function over a VoiceConfig.
"""

from __future__ import annotations

from vortex.line import voice_config


def test_defaults_when_db_empty(offline_settings) -> None:
    cfg = voice_config.load(offline_settings)
    assert cfg == voice_config.VoiceConfig()
    assert voice_config.db_path(offline_settings).name == "voiceconfig.db"


def test_round_trip_persists(offline_settings) -> None:
    voice_config.save(offline_settings, {"voice": "male", "tone": 80, "speechRate": 20})
    cfg = voice_config.load(offline_settings)
    assert cfg.voice == "male"
    assert cfg.tone == 80
    assert cfg.speech_rate == 20
    # Unset fields keep the defaults.
    assert cfg.friendliness == 50


def test_partial_save_keeps_stored_fields(offline_settings) -> None:
    voice_config.save(offline_settings, {"voice": "male"})
    voice_config.save(offline_settings, {"tone": 90})
    cfg = voice_config.load(offline_settings)
    assert cfg.voice == "male"
    assert cfg.tone == 90


def test_clamps_and_rejects_garbage(offline_settings) -> None:
    cfg = voice_config.save(
        offline_settings,
        {"voice": "robot", "tone": 900, "friendliness": -5, "speechRate": "loud"},
    )
    assert cfg.voice == "female"
    assert cfg.tone == 100
    assert cfg.friendliness == 0
    assert cfg.speech_rate == 50


def test_wire_shape_is_camelcase(offline_settings) -> None:
    d = voice_config.save(offline_settings, {}).to_dict()
    assert "speechRate" in d and "speech_rate" not in d


def test_preview_merges_over_stored(offline_settings) -> None:
    voice_config.save(offline_settings, {"voice": "male", "tone": 10})
    cfg = voice_config.preview_config(offline_settings, {"tone": 70})
    assert cfg.voice == "male"  # stored value survives
    assert cfg.tone == 70  # unsaved slider wins
    # ...and nothing was written.
    assert voice_config.load(offline_settings).tone == 10


def test_speaking_rate_mapping() -> None:
    neutral = voice_config.VoiceConfig(speech_rate=50)
    slow = voice_config.VoiceConfig(speech_rate=0)
    fast = voice_config.VoiceConfig(speech_rate=100)
    assert voice_config.speaking_rate(neutral) == 1.0
    assert voice_config.speaking_rate(slow) < 1.0 < voice_config.speaking_rate(fast)
    assert voice_config.elevenlabs_speed(slow) >= 0.7
    assert voice_config.elevenlabs_speed(fast) <= 1.2


def test_apply_gender() -> None:
    chirp = "es-ES-Chirp3-HD-Aoede"
    assert voice_config.apply_gender(chirp, "male") == "es-ES-Chirp3-HD-Charon"
    assert voice_config.apply_gender(chirp, "female") == chirp
    assert voice_config.apply_gender("Aoede", "male") == "Charon"
    # A non-Chirp id is left alone rather than mangled.
    assert voice_config.apply_gender("es-ES-Standard-A", "male") == "es-ES-Standard-A"


def test_style_directive() -> None:
    assert voice_config.style_directive(voice_config.VoiceConfig()) == ""
    formal = voice_config.VoiceConfig(tone=10)
    assert "formal" in voice_config.style_directive(formal)
    warm = voice_config.VoiceConfig(friendliness=90)
    assert "warm" in voice_config.style_directive(warm)
