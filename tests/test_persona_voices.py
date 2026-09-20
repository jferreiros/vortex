"""Which ElevenLabs voice each persona speaks with.

The whole matrix, walked: three personas x five languages x two genders. No
key and no network — the map is a pure function and the ids are literals
verified against the team's ElevenLabs account on 20 Sep 2026.
"""

from __future__ import annotations

import pytest

from vortex import settings as settings_module
from vortex.conversation.language import (
    ALEJANDRO,
    ERIC,
    GEORGE,
    MATILDA,
    PERSONA_VOICES,
    SOFIA,
    SUPPORTED_LANGUAGES,
    VoicePreset,
    elevenlabs_model_for,
    elevenlabs_voice_id,
    persona_voice,
    voice_label,
)

GENDERS = ("female", "male")

#: Every id the map may return. A voice outside this set is a typo that would
#: 404 on ElevenLabs and leave a call mute.
ACCOUNT_VOICES = {SOFIA, ALEJANDRO, MATILDA, ERIC, GEORGE}


def test_every_combination_resolves_to_a_real_id() -> None:
    """3 personas x 5 languages x 2 genders = 30 answers, all of them ids."""
    seen = set()
    for slug in PERSONA_VOICES:
        for language in SUPPORTED_LANGUAGES:
            for gender in GENDERS:
                voice, model = persona_voice(slug, language, gender)
                assert voice in ACCOUNT_VOICES, (slug, language, gender)
                assert model == "", "no persona overrides the model yet"
                seen.add(voice)
    assert len(seen) == 3, "the 30 combinations collapse to three voices: two women, one man"


def test_a_language_never_changes_the_voice() -> None:
    """Every id in the map is multilingual, which is why there are five and
    not thirty: a persona sounds the same in Catalan as in English."""
    for slug in PERSONA_VOICES:
        for gender in GENDERS:
            ids = {persona_voice(slug, code, gender)[0] for code in SUPPORTED_LANGUAGES}
            assert len(ids) == 1, (slug, gender)


def test_the_default_persona_keeps_todays_sound() -> None:
    """``lucia`` is the first seed, so she is who a fresh clinic answers with.
    Her pair is what the preset has always returned: activating nothing
    changes nothing."""
    assert persona_voice("lucia", "es", "female")[0] == VoicePreset.ES.female
    assert persona_voice("lucia", "es", "male")[0] == VoicePreset.ES.male


def test_each_persona_has_its_own_voice() -> None:
    """The point of the feature: three receptionists, three ways of sounding."""
    spoken = {slug: persona_voice(slug, "es", "female")[0] for slug in ("lucia", "carla")}
    assert spoken["lucia"] != spoken["carla"]
    males = {slug: persona_voice(slug, "es", "male")[0] for slug in PERSONA_VOICES}
    assert set(males.values()) == {ALEJANDRO}, "every male switch is Alejandro"


def test_an_unknown_persona_falls_back_to_the_preset() -> None:
    """A persona somebody just created on the Clinic View still sounds like
    the clinic rather than like nothing."""
    assert persona_voice("brand-new", "es", "female")[0] == VoicePreset.ES.female
    assert persona_voice("brand-new", "en", "male")[0] == VoicePreset.EN.male


def test_it_never_raises_on_junk() -> None:
    """This runs inside a live call. A bad slug must not end it."""
    assert persona_voice(None)[0] == VoicePreset.EN.female
    assert persona_voice("")[0] == VoicePreset.EN.female
    assert persona_voice("  LUCIA  ", "es", "female")[0] == SOFIA
    assert persona_voice("lucia", "klingon", "robot")[0] == SOFIA


def test_the_env_override_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """A machine told to use one voice uses it; /voice-current says so."""
    monkeypatch.setenv("ELEVENLABS_VOICE_ID_ES", "voice-env")
    monkeypatch.delenv("ELEVENLABS_VOICE_ID_DEFAULT", raising=False)
    settings_module.reset_settings()
    try:
        s = settings_module.get_settings()
        assert elevenlabs_voice_id("es", s, "female", "carla") == "voice-env"
        # English is untouched by the Spanish-only override.
        assert elevenlabs_voice_id("en", s, "female", "carla") == MATILDA
        # Male has never taken the override: it would land on a female voice.
        assert elevenlabs_voice_id("es", s, "male", "carla") == ALEJANDRO
    finally:
        settings_module.reset_settings()


def test_the_model_defaults_to_the_configured_one() -> None:
    class Stub:
        elevenlabs_model = "eleven_flash_v2_5"

    assert elevenlabs_model_for("lucia", Stub()) == "eleven_flash_v2_5"
    assert elevenlabs_model_for(None, Stub()) == "eleven_flash_v2_5"
    # Nothing configured at all still names a model the account can speak.
    assert elevenlabs_model_for("lucia", object()) == "eleven_flash_v2_5"


def test_a_persona_can_carry_its_own_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Moving one receptionist off flash is a line in the map, not a change
    at four call sites."""
    from vortex.conversation import language

    monkeypatch.setitem(language.PERSONA_MODELS, "carla", "eleven_multilingual_v2")

    class Stub:
        elevenlabs_model = "eleven_flash_v2_5"

    assert elevenlabs_model_for("carla", Stub()) == "eleven_multilingual_v2"
    assert elevenlabs_model_for("lucia", Stub()) == "eleven_flash_v2_5"


def test_voice_labels_name_every_id_in_the_map() -> None:
    """The picker shows a name, not an opaque id."""
    for female, male in PERSONA_VOICES.values():
        for voice in (female, male):
            assert voice_label(voice) != voice
    # An override the team never chose has no name to show; the id will do.
    assert voice_label("voice-env") == "voice-env"
