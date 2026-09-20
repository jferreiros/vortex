"""The wall's "Voz del agente" card, persisted.

One row (``id = 1``) in ``public.voiceconfig``, reached through PostgREST.
Both the line and the board talk to the same table, so the line's
``GET/PUT /voice-config`` and the board's proxy of it can never disagree.

With no store configured a read returns the defaults — a call must sound the
same whether or not somebody set up Supabase — and a write raises
``RuntimeError``, which the HTTP layer turns into a 503.

Each field applies to *new* calls only — pipelines read the config when the
socket builds, which is why the card can say "aplica a llamadas nuevas":

- ``voice``        female | male — picks the ElevenLabs voice id to speak with
- ``speech_rate``  0-100 -> ElevenLabs ``speed``
- ``tone``         0-100 -> a style line appended to the system prompt
- ``friendliness`` 0-100 -> same
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

log = logging.getLogger("vortex.line.voice_config")

VOICES = ("female", "male")

#: The preview speaks the Spanish greeting: same words the line opens with.
PREVIEW_TEXT = "Clínica Arenal, buenos días. ¿En qué puedo ayudarle?"

#: What the card's Ritmo button speaks. Deliberately generic and a little
#: longer than the greeting — it names no persona and no clinic, so the same
#: words can be compared between two receptionists and two speeds, and what
#: changes is only how it sounds.
TEST_TEXT = "Hola, esta es la voz que atiende el teléfono. Uno, dos, tres. ¿Me oye bien?"

#: MP3 for everything pre-rendered: Twilio's <Play> and the wall's Try button.
PREVIEW_OUTPUT_FORMAT = "mp3_44100_128"

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


def elevenlabs_speed(cfg: VoiceConfig) -> float:
    """Slider 0-100 -> ElevenLabs' narrow 0.7-1.2 speed range, centred on 1.0."""
    return round(max(0.7, min(1.2, 1.0 + (cfg.speech_rate - 50) * 0.005)), 2)


def apply_gender(voice_id: str, gender: str, male_voice_id: str = "") -> str:
    """The voice id to speak with, given the card's female/male switch.

    An ElevenLabs voice id is opaque, so a male persona is its own id rather
    than a name to rewrite. With none configured the female voice stands —
    better the configured voice than a made-up one.
    """
    if gender == "male" and male_voice_id:
        return male_voice_id
    return voice_id


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
    settings: Any,
    cfg: VoiceConfig,
    text: str,
    *,
    language_code: str,
    voice_name: str,
    model_id: str = "",
) -> bytes:
    """One MP3 of ``text``, straight through the ElevenLabs HTTP API — no pipeline.

    Blocking on purpose: both callers run it in a worker thread. Raises when
    ``ELEVENLABS_API_KEY`` is empty or the request fails, which is what keeps
    the callers' ``<Say>`` fallback and the preview route's 503 honest.

    ``model_id`` is the persona's model when it has one of its own; empty
    falls back to ``ELEVENLABS_MODEL``, which every voice in the map is built
    for.
    """
    import httpx

    api_key = getattr(settings, "elevenlabs_api_key", "")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set: cannot synthesize")
    if not voice_name:
        raise RuntimeError("no ElevenLabs voice id configured: cannot synthesize")

    base = getattr(settings, "elevenlabs_http_base_url", "https://api.elevenlabs.io")
    response = httpx.post(
        f"{base}/v1/text-to-speech/{voice_name}",
        params={"output_format": PREVIEW_OUTPUT_FORMAT},
        headers={"xi-api-key": api_key},
        json={
            "text": text,
            "model_id": (
                model_id or getattr(settings, "elevenlabs_model", "") or "eleven_flash_v2_5"
            ),
            # A multilingual model needs the bare code to pick the accent.
            "language_code": (language_code or "es").replace("_", "-").split("-", 1)[0].lower(),
            "voice_settings": {"speed": elevenlabs_speed(cfg)},
        },
        timeout=30.0,
    )
    response.raise_for_status()
    return response.content


def preview_voice_id(settings: Any, cfg: VoiceConfig, persona: str | None = None) -> str:
    """The Spanish voice id the Try button speaks with, female or male.

    ``persona`` is the receptionist on the phone. None asks who that is, so
    the button always previews the voice the next call will actually use.
    """
    from vortex.conversation.language import elevenlabs_voice_id

    return elevenlabs_voice_id("es", settings, cfg.voice, persona or active_persona(settings))


def active_persona(settings: Any = None) -> str:
    """The slug of the receptionist on the phone. Never raises: with no store
    it is the first seed, the same one a call would answer with."""
    from vortex.line import personalities

    return personalities.active(settings).slug


def current_voice(settings: Any = None, cfg: VoiceConfig | None = None) -> dict[str, Any]:
    """Which voice the next call will speak with, resolved.

    The truth, not the map: who is on the phone, which ElevenLabs id that
    comes out as, which model says it, and — when an ``ELEVENLABS_VOICE_ID_*``
    variable is set on this machine — that the persona is not what decided it.
    Served at ``/voice-current`` on both front doors: the one way to answer
    "which voice is live right now?" without reading the code. Never raises.
    """
    from vortex.conversation.language import elevenlabs_model_for, persona_voice, voice_label
    from vortex.line import personalities

    config = cfg or load(settings)
    person = personalities.active(settings)
    voice = preview_voice_id(settings, config, person.slug)
    # What the map alone would have said. A difference means a machine-level
    # ELEVENLABS_VOICE_ID_* is in force and the picker is not deciding.
    mapped, _ = persona_voice(person.slug, "es", config.voice)
    return {
        "persona": person.slug,
        "name": person.name,
        "gender": config.voice,
        "voice_id": voice,
        "voice_label": voice_label(voice),
        "model": elevenlabs_model_for(person.slug, settings),
        "language": "es",
        "source": "persona" if voice == mapped else "env_override",
        # The words the Ritmo button speaks, so nothing has to keep a second
        # copy of a line that lives here.
        "test_text": TEST_TEXT,
    }


def synthesize_preview(
    settings: Any, cfg: VoiceConfig, persona: str | None = None, text: str | None = None
) -> bytes:
    """One MP3 for the wall: the greeting by default, the generic test line
    when the card asks for it."""
    from vortex.conversation.language import elevenlabs_model_for

    slug = persona or active_persona(settings)
    return synthesize(
        settings,
        cfg,
        text or PREVIEW_TEXT,
        language_code="es",
        voice_name=preview_voice_id(settings, cfg, slug),
        model_id=elevenlabs_model_for(slug, settings),
    )
