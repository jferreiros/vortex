"""Language handling: detect, switch mid-call, constrain the provider.

Owner: the conversation lane.

The clinic answers in **English**. Of the 73 published cases 69 are English,
3 Spanish and 1 Catalan, and problem 11's private pool draws Catalan far more
often than its public cases. English is therefore the default and the other
four are detected, never assumed.

Two signals, and a *move* needs both:

1. Soniox ``stt-rt-v5`` tags every token with the language it heard when
   ``enable_language_identification`` is on. ``TranscriptionFrame.language`` is
   that tag.
2. A word-level marker vote over the transcript, which also covers frames that
   arrive untagged (and the text-mode evals, which have no STT at all).
   Function words decide because they are frequent and rarely shared: "the",
   "would" and "please" are English; "quiero", "cita" and "vale" are Spanish;
   "vull", "hora" and "si us plau" are Catalan.

Leaving the language the call is already in takes the tag *and* the vote
agreeing. One mis-tagged frame used to flip the voice mid-sentence, and Soniox
mistags a short reply in a telephony band often enough for that to happen on a
scored call. When neither signal is decisive the answer is ``current`` and,
failing that, the default. A call in Spanish must not flip to English on an
"ok".

Language constrains a *booking* only in problem 11: pass it into
``find_slots(language=...)`` only when the caller asks for a doctor they can
talk to. Everywhere else any provider is fine.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import only for the annotation
    from pipecat.transcriptions.language import Language

    from vortex.settings import Settings

SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "es", "ca", "gl", "eu")

DEFAULT_LANGUAGE = "en"

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "ca": "Catalan",
    "gl": "Galician",
    "eu": "Basque",
}

# Single words, lowercase, accents kept: the STT writes them accented. A word
# that exists in several languages ("no", "hola", "doctor") is listed in each
# and cancels out; the words unique to a language carry the vote.
_WORDS: dict[str, frozenset[str]] = {
    "en": frozenset(
        """
        the a an and i i'm i'd you my is are was would like need want could can
        please thank thanks hello hi hey good morning afternoon evening
        appointment book booking doctor with for on at to of it that this
        yes yeah okay sure fine right sorry what when where which
        tomorrow today monday tuesday wednesday thursday friday saturday sunday
        next week earliest soonest available name phone number born date
        cancel move change reschedule
        """.split()
    ),
    "es": frozenset(
        """
        el la los las un una unos unas de del al y o que con para por sin
        quiero quería querría necesito me gustaría cita hora consulta doctor
        doctora médico médica hola buenos buenas días tardes noches gracias
        sí vale bueno bien perdón perdone disculpe soy mi es tengo llamo llamaba
        mañana pasado hoy lunes martes miércoles jueves viernes sábado domingo
        semana próxima primera antes posible cuanto nací nacido nacida teléfono
        móvil dni nie apellido apellidos seguro mutua cambiar anular cancelar
        mover
        """.split()
    ),
    "ca": frozenset(
        """
        el la els les un una uns unes de del dels al als i o que amb per sense
        vull voldria necessito hora visita metge metgessa doctora bon dia bona
        tarda nit gràcies sí d'acord bé perdó perdoni sóc soc el meu la meva
        tinc truco trucava demà passat avui dilluns dimarts dimecres dijous
        divendres dissabte diumenge setmana vinent primera abans possible
        aviat vaig néixer nascut nascuda telèfon mòbil cognom cognoms mútua
        canviar anul·lar cancel·lar moure això però també capçalera parli
        parlar català
        """.split()
    ),
    "gl": frozenset(
        """
        o a os as un unha uns unhas do da dos das ao á e ou que con para por
        sen quero quería necesito cita hora consulta doutor doutora médico
        médica ola bos bo días tardes noites grazas si vale ben perdón
        desculpe son o meu a miña teño chamo chamaba mañá pasado hoxe luns
        martes mércores xoves venres sábado domingo semana próxima primeira
        antes posible nacín nacido nacida teléfono móbil apelido apelidos
        seguro cambiar anular cancelar mover moitas
        """.split()
    ),
    "eu": frozenset(
        """
        egun on arratsalde gabon kaixo eskerrik asko mesedez bai ez nahi dut
        dut behar hitzordua kontsulta medikua sendagilea naiz nire izena
        telefonoa jaio nintzen bihar gaur astelehena asteartea asteazkena
        osteguna ostirala larunbata igandea astea lehen aukera ahalik azkarren
        bertan behera utzi aldatu mugitu deitzen
        """.split()
    ),
}

# Multi-word markers, counted on top of the word vote. Cheap and decisive.
_PHRASES: dict[str, tuple[str, ...]] = {
    "en": ("good morning", "i would like", "i'd like", "thank you", "i need"),
    "es": ("buenos días", "buenas tardes", "por favor", "lo antes posible", "quería cita"),
    "ca": ("bon dia", "bona tarda", "si us plau", "com abans millor", "voldria hora"),
    "gl": ("bos días", "boas tardes", "moitas grazas", "canto antes"),
    "eu": ("egun on", "eskerrik asko", "arratsalde on"),
}

# Words that, alone, do not prove a language: they appear in several and are
# the whole content of a short reply ("no", "ok", "hola").
_PHRASE_WEIGHT = 2


def normalise_language(code: object) -> str | None:
    """Fold any language code (``Language.ES_ES``, ``"es-ES"``, ``"es"``) to ours."""
    if code is None:
        return None
    try:
        text = str(getattr(code, "value", code)).strip().lower()
    except Exception:  # never let a stray object break a live call
        return None
    if not text:
        return None
    base = text.replace("_", "-").split("-", 1)[0]
    return base if base in SUPPORTED_LANGUAGES else None


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    word = []
    for ch in text.lower():
        if ch.isalnum() or ch in "'’·":
            word.append("'" if ch == "’" else ch)
        elif word:
            out.append("".join(word))
            word = []
    if word:
        out.append("".join(word))
    return out


def language_scores(transcript: str) -> dict[str, int]:
    """How many marker words and phrases of each language the transcript holds."""
    text = (transcript or "").lower()
    tokens = _tokens(text)
    scores: dict[str, int] = {}
    for code in SUPPORTED_LANGUAGES:
        words = _WORDS[code]
        score = sum(1 for t in tokens if t in words)
        score += _PHRASE_WEIGHT * sum(1 for p in _PHRASES[code] if p in text)
        scores[code] = score
    return scores


def detect_language(transcript: str, hint: object | None = None, current: str | None = None) -> str:
    """Return an ISO-639-1 code from ``SUPPORTED_LANGUAGES``.

    ``hint`` is the per-token language Soniox reports on the transcription
    frame. It does **not** win on its own: one mis-tagged frame used to flip
    the whole call's voice mid-sentence, and Soniox mistags a short reply in a
    noisy telephony band often enough to matter. So a hint that would move the
    call needs the word vote to agree with it; a hint that matches the language
    the call is already in is accepted as confirmation. Otherwise the marker
    vote decides alone, and a transcript with no decisive marker keeps
    ``current``. Never raises.
    """
    fallback = normalise_language(current) or DEFAULT_LANGUAGE
    from_hint = normalise_language(hint)
    if from_hint == fallback:
        return fallback
    try:
        scores = language_scores(transcript)
    except Exception:
        return fallback
    best = max(scores.values(), default=0)
    if from_hint:
        # A move needs two signals. The vote agrees when the hinted language is
        # among the languages the transcript scored highest.
        if best > 0 and scores.get(from_hint, 0) == best:
            return from_hint
        return fallback
    if best == 0:
        return fallback
    winners = [code for code, score in scores.items() if score == best]
    if len(winners) == 1:
        return winners[0]
    # A tie between the language we are in and another: stay put.
    if fallback in winners:
        return fallback
    # A tie among other languages: the first in the supported order (English
    # first, then Spanish) is the least surprising choice on this line.
    return winners[0]


def language_name(code: str | None) -> str:
    return LANGUAGE_NAMES.get(normalise_language(code) or DEFAULT_LANGUAGE, "English")


#: ElevenLabs takes a bare code; the regional one only earns a "not verified"
#: warning on the way through pipecat's resolver.
_PIPECAT_LANGUAGE_NAMES: dict[str, str] = {
    "en": "EN",
    "es": "ES",
    "ca": "CA",
    "gl": "GL",
    "eu": "EU",
}


class VoicePreset(Enum):
    """Which ElevenLabs voice speaks which language, female and male.

    ElevenLabs' multilingual models speak all five languages out of one voice,
    so this is a persona map, not a translation table: the same pair serves
    every language until somebody has a reason to split one off. It is a fixed
    preset in code on purpose — a voice id is a tuning decision the team makes
    together, not a per-machine environment variable. The wall's female/male
    switch picks the column; ``ELEVENLABS_VOICE_ID_DEFAULT`` (every language)
    and ``ELEVENLABS_VOICE_ID_ES`` (Spanish only) override the female one.

    The value is ``(female_voice_id, male_voice_id)``. Both are the team's
    professional Spanish voices, verified on the account on 20 Sep 2026:
    ``Sofia - Natural Conversations`` and ``Alejandro de la Mancha``. A
    multilingual model carries the same two through the other four languages,
    which is why every row repeats them.
    """

    EN = ("eZxqQzb5CuYo3Kl6EXfZ", "JngPf0lmRkKhY3qSJz0f")
    ES = ("eZxqQzb5CuYo3Kl6EXfZ", "JngPf0lmRkKhY3qSJz0f")
    CA = ("eZxqQzb5CuYo3Kl6EXfZ", "JngPf0lmRkKhY3qSJz0f")
    GL = ("eZxqQzb5CuYo3Kl6EXfZ", "JngPf0lmRkKhY3qSJz0f")
    EU = ("eZxqQzb5CuYo3Kl6EXfZ", "JngPf0lmRkKhY3qSJz0f")

    @property
    def female(self) -> str:
        return self.value[0]

    @property
    def male(self) -> str:
        return self.value[1]


def voice_preset_for(language: str | None) -> VoicePreset:
    """The preset row for a language. Anything outside the five gets English."""
    code = normalise_language(language) or DEFAULT_LANGUAGE
    return VoicePreset[code.upper()]


def elevenlabs_voice_id(
    language: str | None, settings: Settings | Any = None, gender: str = "female"
) -> str:
    """The voice id to speak ``language`` with, preset first, env override on top.

    Male comes from the preset alone: it is the second column of the same row,
    so the switch never lands on a voice nobody chose.
    """
    preset = voice_preset_for(language)
    if gender == "male":
        return preset.male
    code = normalise_language(language) or DEFAULT_LANGUAGE
    override = str(getattr(settings, "elevenlabs_voice_id_default", "") or "")
    if code == "es":
        override = str(getattr(settings, "elevenlabs_voice_id_es", "") or "") or override
    return override or preset.female


def tts_voice_for(
    language: str, settings: Settings | Any, provider: str | None = None, gender: str = "female"
) -> tuple[str, Language]:
    """The voice id and the pipecat ``Language`` for a detected language.

    One provider (ElevenLabs) and one multilingual model, so a language switch
    is a new voice id on the running service. ``provider`` is kept for callers
    that still name the service; there is only one to name.

    Anything outside the five falls back to English, the clinic's default.
    Never raises: a failed lookup during a live call must not end the call.
    """
    from pipecat.transcriptions.language import Language

    code = normalise_language(language) or DEFAULT_LANGUAGE
    voice = elevenlabs_voice_id(code, settings, gender)
    tts_language = getattr(Language, _PIPECAT_LANGUAGE_NAMES[code], Language.EN)
    return str(voice or ""), tts_language
