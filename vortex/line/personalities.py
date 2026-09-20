"""The receptionist personas the Clinic View picker offers.

A personality is the face and the voice the clinic puts on the line: a name, a
role, a blurb for the card, a short tone fragment for the system prompt, one
greeting and one TTS voice per language, and a portrait.

Stored exactly like the "Voz del agente" card (``voice_config.py``): rows in
``public.personalities``, reached through PostgREST. The line and the board
read the same table, so the board's proxy of ``/personalities`` and the line's
own answer can never disagree.

With no store configured, reads fall back to the three seeds — a clinic never
boots without a receptionist — and writes raise ``RuntimeError``, which the
routes turn into a 503.

Exactly one persona is active at a time. ``activate`` is the only way to move
that flag: it clears every other row first and only then sets the new one, so
the worst a half-applied write can leave behind is a clinic with no active
persona, which ``active()`` already answers from the seeds.

The call reads the active persona once per socket (``pipecat_voice``): its name,
role and tone become the prompt's PERSONA block, its greeting opens the line,
and its slug picks the ElevenLabs voice and model the line speaks with, from
``conversation.language.PERSONA_VOICES``.

``voices`` is the one stored field the call ignores — those are leftover Google
Chirp names, and a voice id is a tuning decision that belongs in the map, not
in a form field that can hold a string ElevenLabs has never heard of.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

log = logging.getLogger("vortex.line.personalities")

#: The languages the clinic answers in. ``greetings`` and ``voices`` may be
#: partial, but a key outside this tuple is a typo, not a new language.
LANGUAGES: tuple[str, ...] = ("en", "es", "ca", "gl", "eu")

#: The system prompt is capped at roughly 1400 tokens and goes out on every
#: turn, so a persona's tone has to stay a fragment, not a second prompt.
TONE_MAX_CHARS = 400

#: A persona carries no voice id in the store: which ElevenLabs voice each
#: receptionist speaks with is ``conversation.language.PERSONA_VOICES``, a
#: fixed map in code the team tunes together, not a field a form can set to a
#: string ElevenLabs has never heard of. These two stay empty so the stored
#: row says "ask the map": ``conversation.language.persona_voice`` is the ask.
VOICE_ES = ""
VOICE_EN = ""

#: Vorty heads from ``vortex/wall/media``: the bare face plus one accessory
#: overlay. ``none`` is the face without a hat. The picker stores the stem
#: (``headset.svg``) in ``avatar``.
LOOKS: tuple[str, ...] = (
    "none",
    "headset",
    "beanie",
    "baseball-cap",
    "sunglasses",
    "halo",
    "bow-tie",
    "antenna",
)

#: Three ways of talking, in words a receptionist would pick. The English
#: ``tone`` is what the model sees; ``label`` / ``hint`` / ``role`` /
#: ``description`` are what the Clinic View shows.
STYLES: dict[str, dict[str, str]] = {
    "warm": {
        "label": "Cálida",
        "hint": "Saluda, usa el nombre y confirma la cita sin prisa.",
        "role": "Recepcionista de mostrador",
        "description": (
            "Saluda, se toma el tiempo de anotar bien el nombre y la fecha, y "
            "repite la cita antes de colgar."
        ),
        "tone": (
            "Warm and unhurried. Greet the patient, then use their first name once you "
            "have it. Say one thing at a time and wait. Read the appointment back before "
            "you confirm it. When you have to refuse, name the rule in plain words and "
            "offer the nearest thing you can do."
        ),
    },
    "brisk": {
        "label": "Directa",
        "hint": "Va al grano y ofrece dos huecos, no diez.",
        "role": "Especialista en agenda",
        "description": (
            "Va directo a la agenda, ofrece dos huecos en vez de diez y acorta la "
            "llamada sin cortar al paciente."
        ),
        "tone": (
            "Brisk and precise. Get to the diary quickly. Offer at most two slots and "
            "name the day, the time and the site. Confirm in one sentence. Never rush "
            "the patient, but do not fill silence with small talk."
        ),
    },
    "calm": {
        "label": "Tranquila",
        "hint": "Repite lo que ha oído y no tiene prisa.",
        "role": "Coordinadora de atención al paciente",
        "description": (
            "Baja el ritmo, repite lo que ha entendido y comprueba que el paciente "
            "la sigue antes de continuar."
        ),
        "tone": (
            "Calm and steady. Repeat back what the patient told you before you act on "
            "it. Ask one short question at a time and leave room for an answer. If the "
            "patient sounds worried, say what happens next before you ask for anything "
            "else. Escalate rather than guess."
        ),
    },
}


def greetings_for(name: str) -> dict[str, str]:
    return {
        "es": f"Clínica Arenal, le atiende {name}. ¿En qué puedo ayudarle?",
        "en": f"Clínica Arenal, {name} speaking. How can I help you?",
    }


def style_fields(style_id: str) -> dict[str, str]:
    style = STYLES.get(style_id) or STYLES["warm"]
    return {key: style[key] for key in ("role", "description", "tone")}


def normalize_look(value: str) -> str:
    stem = value.strip().removesuffix(".svg").lower()
    if stem not in LOOKS:
        raise ValueError("pick a look from the faces on the form")
    return "none" if stem == "none" else f"{stem}.svg"


def slug_from_name(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name)
    ascii_ = "".join(ch for ch in folded if not unicodedata.combining(ch))
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")
    return slug or "persona"


def catalog() -> dict[str, Any]:
    """The simple picker: three ways of talking, the Vorty looks."""
    return {
        "styles": [
            {"id": key, "label": row["label"], "hint": row["hint"]} for key, row in STYLES.items()
        ],
        "looks": list(LOOKS),
    }


def listing(settings: Any = None) -> dict[str, Any]:
    """The picker's whole payload: the rail, who is on the phone, the catalogue.

    Both front doors answer with this exact dict — the line's
    ``GET /personalities`` and the board's ``GET /api/wall/personalities``.
    They read the same table, so the shape is defined once here rather than
    written out twice and drifting.

    No voice id here: the rail is a picker of faces. Which ElevenLabs voice
    the active one ends up speaking with is ``voice_config.current_voice``,
    served at ``/voice-current``.
    """
    people = list_all(settings)
    return {
        "items": [person.to_dict() for person in people],
        "active": next((person.slug for person in people if person.active), None),
        **catalog(),
    }


_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
#: A portrait is a bare filename inside ``vortex/wall/media/personalities``. No
#: separator, no leading dot: the route that serves the art joins this to the
#: folder, and a name that can climb out of it is a file disclosure.
_AVATAR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_COLUMNS = (
    "slug",
    "name",
    "role",
    "description",
    "tone",
    "greetings_json",
    "voices_json",
    "avatar",
    "sort_order",
    "active",
    "created_at",
    "updated_at",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class PersonalityDraft(BaseModel):
    """Everything a human edits on the Personalities page.

    The slug, the active flag and the timestamps are the store's business, so
    they are not here: a draft cannot rename a row or make itself active.
    """

    name: str
    role: str
    description: str
    tone: str
    greetings: dict[str, str] = Field(default_factory=dict)
    voices: dict[str, str] = Field(default_factory=dict)
    avatar: str
    sort_order: int = 0

    @field_validator("name", "role", "description")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("this field cannot be empty")
        return text

    @field_validator("tone")
    @classmethod
    def _tone_fits_the_prompt(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("the tone cannot be empty")
        if len(text) > TONE_MAX_CHARS:
            raise ValueError(
                f"the tone is {len(text)} characters; it rides in the system prompt on "
                f"every turn, so keep it under {TONE_MAX_CHARS}"
            )
        return text

    @field_validator("greetings", "voices")
    @classmethod
    def _known_languages(cls, value: dict[str, str]) -> dict[str, str]:
        unknown = sorted(set(value) - set(LANGUAGES))
        if unknown:
            raise ValueError(f"not a language the clinic speaks: {', '.join(unknown)}")
        return {code: text.strip() for code, text in value.items() if text.strip()}

    @field_validator("avatar")
    @classmethod
    def _avatar_is_a_bare_filename(cls, value: str) -> str:
        if not _AVATAR.match(value.strip()):
            raise ValueError(
                "the avatar is a filename inside vortex/wall/media/personalities, "
                "with no path separator"
            )
        return value.strip()


class Personality(PersonalityDraft):
    """A stored persona: a draft plus the fields only the store may set."""

    slug: str
    active: bool = False
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)

    @field_validator("slug")
    @classmethod
    def _slug_is_kebab(cls, value: str) -> str:
        if not _SLUG.match(value):
            raise ValueError("the slug is lowercase words joined by hyphens, e.g. front-desk")
        return value

    def to_dict(self) -> dict[str, Any]:
        """The wire shape. Plain snake_case: the Personalities page is new and
        reads these names straight, unlike the older voice card."""
        return self.model_dump(mode="json")


#: The three personas a fresh database opens with. Portraits are Vorty's
#: head plus an accessory from ``vortex/wall/media/accessories``.
SEEDS: tuple[Personality, ...] = (
    Personality(
        slug="lucia",
        name="Lucía",
        **style_fields("warm"),
        greetings=greetings_for("Lucía"),
        voices={"es": VOICE_ES, "en": VOICE_EN},
        avatar="headset.svg",
        sort_order=0,
    ),
    Personality(
        slug="mateo",
        name="Mateo",
        **style_fields("brisk"),
        greetings=greetings_for("Mateo"),
        voices={"es": VOICE_ES, "en": VOICE_EN},
        avatar="baseball-cap.svg",
        sort_order=1,
    ),
    Personality(
        slug="carla",
        name="Carla",
        **style_fields("calm"),
        greetings=greetings_for("Carla"),
        voices={"es": VOICE_ES, "en": VOICE_EN},
        avatar="beanie.svg",
        sort_order=2,
    ),
)

#: The seeds as wire dicts, with the first one active: what the board serves
#: when the line is down, so the page still renders something true-ish.
DEFAULTS: list[dict[str, Any]] = [
    {**person.to_dict(), "active": index == 0} for index, person in enumerate(SEEDS)
]


# --- the table ---------------------------------------------------------------

TABLE = "personalities"

#: Seeds are written once, the first time the table is read empty. A flag, not
#: a lock: the write is an upsert on ``slug``, so two processes racing here
#: land the same three rows.
_seeded = False


def _params(person: Personality) -> dict[str, Any]:
    """One persona as the table stores it: the two dicts folded into json
    columns, ``active`` as the integer the schema declares."""
    data = person.to_dict()
    return {
        **{key: data[key] for key in _COLUMNS if key in data},
        "greetings_json": json.dumps(data["greetings"], ensure_ascii=False),
        "voices_json": json.dumps(data["voices"], ensure_ascii=False),
        "active": 1 if person.active else 0,
    }


def _from_row(row: dict[str, Any]) -> Personality:
    return Personality(
        slug=row["slug"],
        name=row["name"],
        role=row["role"],
        description=row["description"],
        tone=row["tone"],
        greetings=json.loads(row.get("greetings_json") or "{}"),
        voices=json.loads(row.get("voices_json") or "{}"),
        avatar=row["avatar"],
        sort_order=row.get("sort_order") or 0,
        active=bool(row.get("active")),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _seeds(active_first: bool = True) -> list[Personality]:
    return [
        person.model_copy(update={"active": active_first and index == 0})
        for index, person in enumerate(SEEDS)
    ]


def _require_store() -> Any:
    from database import remote

    if not remote.enabled():
        raise RuntimeError(
            "no store configured: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY "
            "to edit personalities"
        )
    return remote


def _rows(params: dict[str, str]) -> list[dict[str, Any]] | None:
    from database import remote

    try:
        return remote.select(TABLE, params)
    except Exception as exc:
        log.warning("personalities unreadable: %s", exc)
        return None


def _seed_once() -> None:
    """A clinic never boots without a receptionist, so an empty table gets the
    three seeds with the first one on the phone."""
    global _seeded
    if _seeded:
        return
    from database import remote

    if not remote.enabled():
        return
    try:
        remote.upsert(TABLE, [_params(person) for person in _seeds()], "slug")
        _seeded = True
    except Exception:
        log.exception("could not seed personalities")


# --- reading ------------------------------------------------------------------


def list_all(settings: Any = None) -> list[Personality]:
    """Every persona, in the order the rail shows them.

    An empty or unreachable table answers with the seeds rather than nothing:
    the picker showing three faces nobody chose beats a blank rail.
    """
    rows = _rows({"select": "*", "order": "sort_order.asc,name.asc"})
    if rows:
        return [_from_row(row) for row in rows]
    if rows is not None:
        _seed_once()
    return _seeds()


def get(settings: Any, slug: str) -> Personality | None:
    rows = _rows({"select": "*", "slug": f"eq.{slug}", "limit": "1"})
    if rows:
        return _from_row(rows[0])
    if rows is None:
        return None
    return next((person for person in list_all(settings) if person.slug == slug), None)


def active(settings: Any = None) -> Personality:
    """The persona answering the phone. Falls back to the first seed rather
    than raising: an unreachable store must not stop a call from being
    answered."""
    rows = _rows(
        {"select": "*", "active": "eq.1", "order": "sort_order.asc,name.asc", "limit": "1"}
    )
    if rows:
        return _from_row(rows[0])
    if rows is not None:
        log.warning("no active personality stored, falling back to %s", SEEDS[0].slug)
    return SEEDS[0].model_copy(update={"active": True})


# --- writing ------------------------------------------------------------------


def update(settings: Any, slug: str, payload: dict[str, Any] | None) -> Personality:
    """Apply the edit form to one persona.

    Raises ``KeyError`` when the slug is unknown and ``pydantic.ValidationError``
    when the form does not hold — the route turns those into 404 and 422.
    ``ValueError`` is a bad ``style`` or ``look`` from the simple picker, and
    ``RuntimeError`` is no store at all (503).
    """
    remote = _require_store()
    current = get(settings, slug)
    if current is None:
        raise KeyError(slug)
    incoming = dict(payload or {})
    name = str(incoming.get("name") or current.name).strip()
    if incoming.get("style"):
        if incoming["style"] not in STYLES:
            raise ValueError("pick how they talk: cálida, directa or tranquila")
        incoming.update(style_fields(incoming.pop("style")))
        incoming["greetings"] = greetings_for(name)
    if "look" in incoming:
        incoming["avatar"] = normalize_look(str(incoming.pop("look")))
    base = {key: getattr(current, key) for key in PersonalityDraft.model_fields}
    draft = PersonalityDraft(**{**base, **incoming, "name": name})
    stored = current.model_copy(update={**draft.model_dump(), "updated_at": _now()})
    remote.upsert(TABLE, [_params(stored)], "slug")
    return stored


def create(settings: Any, payload: dict[str, Any] | None) -> Personality:
    """A new persona from the simple form: a name, how they talk, a look."""
    remote = _require_store()
    incoming = dict(payload or {})
    name = str(incoming.get("name") or "").strip()
    if not name:
        raise ValueError("ponle un nombre")
    style_id = incoming.get("style") or "warm"
    if style_id not in STYLES:
        raise ValueError("pick how they talk: cálida, directa or tranquila")
    people = list_all(settings)
    base = slug_from_name(name)
    taken = {person.slug for person in people}
    slug = base
    n = 2
    while slug in taken:
        slug = f"{base}-{n}"
        n += 1
    person = Personality(
        slug=slug,
        name=name,
        **style_fields(style_id),
        greetings=greetings_for(name),
        voices={"es": VOICE_ES, "en": VOICE_EN},
        avatar=normalize_look(str(incoming.get("look") or "headset")),
        sort_order=max((person.sort_order for person in people), default=-1) + 1,
        active=False,
    )
    remote.upsert(TABLE, [_params(person)], "slug")
    return person


def activate(settings: Any, slug: str) -> Personality:
    """Put one persona on the phone and take every other one off it.

    Clear first, set second. PostgREST has no transaction across two
    requests, so the order is the safety: a crash between them leaves the
    clinic with no active persona, which ``active()`` answers from the seeds,
    rather than with two receptionists, which nothing can resolve.
    """
    remote = _require_store()
    now = _now()
    people = list_all(settings)
    target = next((person for person in people if person.slug == slug), None)
    if target is None:
        raise KeyError(slug)
    remote.upsert(
        TABLE,
        [
            _params(person.model_copy(update={"active": False, "updated_at": now}))
            for person in people
            if person.slug != slug and person.active
        ],
        "slug",
    )
    stored = target.model_copy(update={"active": True, "updated_at": now})
    remote.upsert(TABLE, [_params(stored)], "slug")
    return stored
