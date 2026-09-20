"""The wall's "Voz del agente" card, persisted.

One row (``id = 1``) in ``public.voiceconfig``, reached through PostgREST.
Both the line and the board talk to the same table, so the line's
``GET/PUT /voice-config`` and the board's proxy of it can never disagree.

With no store configured a read returns the defaults — a call must sound the
same whether or not somebody set up Supabase — and a write raises
``RuntimeError``, which the HTTP layer turns into a 503.

Each field applies to *new* calls only — pipelines read the config when the
socket builds, which is why the card can say "aplica a llamadas nuevas":

- ``voice``        female | male — swaps the Chirp 3 HD persona (Aoede/Charon)
- ``speech_rate``  0-100 -> Google ``speaking_rate`` / ElevenLabs ``speed``
- ``tone``         0-100 -> a style line appended to the system prompt
- ``friendliness`` 0-100 -> same
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any

log = logging.getLogger("vortex.line.voice_config")

VOICES = ("female", "male")

#: Chirp 3 HD persona names. Aoede is the configured default everywhere;
#: Charon is its male counterpart in the same family.
FEMALE_PERSONA = "Aoede"
MALE_PERSONA = "Charon"

#: The preview speaks the Spanish greeting: same words the line opens with.
PREVIEW_TEXT = "Clínica Arenal, buenos días. ¿En qué puedo ayudarle?"
PREVIEW_VOICE = "es-ES-Chirp3-HD-Aoede"

DEFAULTS: dict[str, Any] = {"voice": "female", "tone": 50, "friendliness": 50, "speech_rate": 50}


@dataclass(frozen=True)
class VoiceConfig:
    voice: str = "female"
    tone: int = 50
    friendliness: int = 50
    speech_rate: int = 50

    def to_dict(self) -> dict[str, Any]:
        # The wall card posts/reads camelCase (speechRate); the db column is
        # snake_case. The wire follows the card.
        d = asdict(self)
        d["speechRate"] = d.pop("speech_rate")
        return d


#: The table's one row. A settings card has nothing to key on but itself.
ROW_ID = 1

TABLE = "voiceconfig"


def _clamp(value: Any, lo: int = 0, hi: int = 100) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return (lo + hi) // 2


def _clean(data: dict[str, Any]) -> VoiceConfig:
    voice = str(data.get("voice") or "female").lower()
    # Accept both casings: the db row is speech_rate, the card posts speechRate.
    rate = data.get("speech_rate", data.get("speechRate"))
    return VoiceConfig(
        voice=voice if voice in VOICES else "female",
        tone=_clamp(data.get("tone")),
        friendliness=_clamp(data.get("friendliness")),
        speech_rate=_clamp(rate),
    )


def load(settings: Any = None) -> VoiceConfig:
    """The stored config, or defaults. Never raises: an unreachable store must
    not change how a call sounds."""
    from database import remote

    try:
        rows = remote.select(
            TABLE,
            {"select": "voice,tone,friendliness,speech_rate", "id": f"eq.{ROW_ID}", "limit": "1"},
        )
    except Exception as exc:
        log.warning("voiceconfig unreadable, using defaults: %s", exc)
        return VoiceConfig()
    if not rows:
        return VoiceConfig()
    return _clean(dict(rows[0]))


def save(settings: Any, data: dict[str, Any] | None) -> VoiceConfig:
    """Merge ``data`` over the stored config and write it back.

    Raises ``RuntimeError`` with no store: the card must not report a save
    that went nowhere, so the route turns this into a 503.
    """
    from database import remote

    if not remote.enabled():
        raise RuntimeError(
            "no store configured: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY "
            "to save the voice config"
        )
    cfg = _clean({**load(settings).to_dict(), **(data or {})})
    remote.upsert(
        TABLE,
        [
            {
                "id": ROW_ID,
                "voice": cfg.voice,
                "tone": cfg.tone,
                "friendliness": cfg.friendliness,
                "speech_rate": cfg.speech_rate,
            }
        ],
        "id",
    )
    return cfg


# --- applying it -------------------------------------------------------------


def speaking_rate(cfg: VoiceConfig) -> float:
    """Slider 0-100 -> Google's speaking_rate, centred on 50 = 1.0."""
    return round(1.0 + (cfg.speech_rate - 50) * 0.005, 2)


def elevenlabs_speed(cfg: VoiceConfig) -> float:
    """Same slider, ElevenLabs' narrower 0.7-1.2 range."""
    return round(max(0.7, min(1.2, 1.0 + (cfg.speech_rate - 50) * 0.005)), 2)


def apply_gender(voice_name: str, gender: str) -> str:
    """Swap the persona at the end of a Google voice name.

    ``es-ES-Chirp3-HD-Aoede`` -> ``es-ES-Chirp3-HD-Charon``; a bare Gemini short
    name ``Aoede`` -> ``Charon``. Anything else (Standard-*, a custom id) comes
    back untouched — better the configured voice than a made-up one.
    """
    if gender != "male":
        return voice_name
    if "Chirp3-HD-" in voice_name:
        return voice_name.rsplit("-", 1)[0] + f"-{MALE_PERSONA}"
    if voice_name == FEMALE_PERSONA:
        return MALE_PERSONA
    return voice_name


def gemini_prompt(cfg: VoiceConfig) -> str:
    """Gemini-TTS takes a natural-language prompt instead of a rate field."""
    if cfg.speech_rate <= 33:
        return "Speak slowly and clearly, at a calm pace."
    if cfg.speech_rate >= 66:
        return "Speak quickly but clearly."
    return "Speak at a natural, steady pace."


def style_directive(cfg: VoiceConfig) -> str:
    """One line appended to the system prompt. Empty at neutral (50/50)."""
    parts: list[str] = []
    if cfg.tone <= 33:
        parts.append("Keep a formal, measured tone.")
    elif cfg.tone >= 66:
        parts.append("Keep a warm, informal tone.")
    if cfg.friendliness <= 33:
        parts.append("Be direct and efficient; skip pleasantries.")
    elif cfg.friendliness >= 66:
        parts.append("Be extra warm and reassuring.")
    return ("VOICE STYLE. " + " ".join(parts)) if parts else ""


def preview_config(settings: Any, payload: dict[str, Any] | None) -> VoiceConfig:
    """The Try button posts the card's current slider state, saved or not:
    it merges over the stored config so a preview always reflects the knobs."""
    return _clean({**load(settings).to_dict(), **(payload or {})})


# --- the Try button ----------------------------------------------------------


def synthesize(
    settings: Any, cfg: VoiceConfig, text: str, *, language_code: str, voice_name: str
) -> bytes:
    """One MP3 of ``text``, straight through Google TTS — no pipeline.

    Uses the same credentials the pipeline would. Raises when there are none:
    callers turn that into a 503 or a <Say> fallback.
    """
    from google.cloud import texttospeech
    from google.oauth2 import service_account

    if settings.google_tts_credentials_json:
        creds = service_account.Credentials.from_service_account_info(
            json.loads(settings.google_tts_credentials_json)
        )
        client = texttospeech.TextToSpeechClient(credentials=creds)
    elif settings.google_application_credentials:
        client = texttospeech.TextToSpeechClient.from_service_account_file(
            settings.google_application_credentials
        )
    else:
        client = texttospeech.TextToSpeechClient()

    response = client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=texttospeech.VoiceSelectionParams(language_code=language_code, name=voice_name),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=speaking_rate(cfg),
        ),
    )
    return response.audio_content


def synthesize_preview(settings: Any, cfg: VoiceConfig) -> bytes:
    """One MP3 of the greeting for the wall's Try button."""
    return synthesize(
        settings,
        cfg,
        PREVIEW_TEXT,
        language_code="es-ES",
        voice_name=apply_gender(PREVIEW_VOICE, cfg.voice),
    )
