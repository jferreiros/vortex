"""The receptionist personas the Clinic View picker offers.

A personality is the face and the voice the clinic puts on the line: a name, a
role, a blurb for the card, a short tone fragment for the system prompt, one
greeting and one TTS voice per language, and a portrait.

Stored exactly like the "Voz del agente" card (``voice_config.py``): stdlib
``sqlite3``, one file — ``personalities.db`` — next to the calls log, so in
production it lands on the line's log volume. The line owns the file: the board
only mounts that volume read-only, so it reads and writes through the line's
``/personalities`` routes and never opens the db itself.

Exactly one persona is active at a time. ``activate`` is the only way to move
that flag and it moves it inside a single transaction, so a crash halfway
cannot leave the clinic with two receptionists or none.

Nothing here reaches the phone call yet: this module stores, lists and edits
personas. Reading the active one on the line — the system prompt's tone line,
the opening greeting, the TTS voice — is a separate change.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import unicodedata
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

log = logging.getLogger("vortex.line.personalities")

#: The languages the clinic answers in. ``greetings`` and ``voices`` may be
#: partial, but a key outside this tuple is a typo, not a new language.
LANGUAGES: tuple[str, ...] = ("en", "es", "ca", "gl", "eu")

#: The system prompt is capped at roughly 1400 tokens and goes out on every
#: turn, so a persona's tone has to stay a fragment, not a second prompt.
TONE_MAX_CHARS = 400

#: Same ids ``Settings.google_tts_voice_es`` / ``_en`` default to today, so
#: that once a later change reads a persona on the line nothing about the
#: sound moves unless somebody changed it here on purpose.
VOICE_ES = "es-ES-Chirp3-HD-Aoede"
VOICE_EN = "en-GB-Chirp3-HD-Aoede"

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


# --- the file ----------------------------------------------------------------


def db_path(settings: Any) -> Path:
    override = os.environ.get("VORTEX_PERSONALITIES_DB", "").strip()
    if override:
        return Path(override)
    return settings.calls_log_path.parent / "personalities.db"


def _connect(settings: Any) -> sqlite3.Connection:
    """Open the db, creating and seeding it the first time."""
    path = db_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    with conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS personalities ("
            "slug TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL, "
            "description TEXT NOT NULL, tone TEXT NOT NULL, "
            "greetings_json TEXT NOT NULL, voices_json TEXT NOT NULL, "
            "avatar TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0, "
            "active INTEGER NOT NULL DEFAULT 0, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        empty = conn.execute("SELECT COUNT(*) AS n FROM personalities").fetchone()["n"] == 0
        if empty:
            # A fresh file opens with the three seeds and the first one on the
            # phone: a clinic never boots without a receptionist.
            for index, person in enumerate(SEEDS):
                conn.execute(_INSERT, _params(person.model_copy(update={"active": index == 0})))
    return conn


_INSERT = (
    "INSERT INTO personalities ("
    "slug, name, role, description, tone, greetings_json, voices_json, "
    "avatar, sort_order, active, created_at, updated_at) VALUES ("
    ":slug, :name, :role, :description, :tone, :greetings_json, :voices_json, "
    ":avatar, :sort_order, :active, :created_at, :updated_at) "
    "ON CONFLICT(slug) DO UPDATE SET "
    "name = excluded.name, role = excluded.role, description = excluded.description, "
    "tone = excluded.tone, greetings_json = excluded.greetings_json, "
    "voices_json = excluded.voices_json, avatar = excluded.avatar, "
    "sort_order = excluded.sort_order, active = excluded.active, "
    "updated_at = excluded.updated_at"
)


def _params(person: Personality) -> dict[str, Any]:
    data = person.to_dict()
    return {
        **{key: data[key] for key in _COLUMNS if key in data},
        "greetings_json": json.dumps(data["greetings"], ensure_ascii=False),
        "voices_json": json.dumps(data["voices"], ensure_ascii=False),
        "active": 1 if person.active else 0,
    }


def _from_row(row: sqlite3.Row) -> Personality:
    return Personality(
        slug=row["slug"],
        name=row["name"],
        role=row["role"],
        description=row["description"],
        tone=row["tone"],
        greetings=json.loads(row["greetings_json"] or "{}"),
        voices=json.loads(row["voices_json"] or "{}"),
        avatar=row["avatar"],
        sort_order=row["sort_order"],
        active=bool(row["active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# --- reading ------------------------------------------------------------------


def list_all(settings: Any) -> list[Personality]:
    """Every persona, in the order the rail shows them."""
    with closing(_connect(settings)) as conn:
        rows = conn.execute("SELECT * FROM personalities ORDER BY sort_order, name").fetchall()
    return [_from_row(row) for row in rows]


def get(settings: Any, slug: str) -> Personality | None:
    with closing(_connect(settings)) as conn:
        row = conn.execute("SELECT * FROM personalities WHERE slug = ?", (slug,)).fetchone()
    return _from_row(row) if row is not None else None


def active(settings: Any) -> Personality:
    """The persona answering the phone. Falls back to the first seed rather
    than raising: a broken db must not stop a call from being answered."""
    try:
        with closing(_connect(settings)) as conn:
            row = conn.execute(
                "SELECT * FROM personalities WHERE active = 1 ORDER BY sort_order, name LIMIT 1"
            ).fetchone()
        if row is not None:
            return _from_row(row)
        log.warning("no active personality stored, falling back to %s", SEEDS[0].slug)
    except sqlite3.Error as exc:
        log.warning("personalities unreadable, falling back to %s: %s", SEEDS[0].slug, exc)
    return SEEDS[0].model_copy(update={"active": True})


# --- writing ------------------------------------------------------------------


def update(settings: Any, slug: str, payload: dict[str, Any] | None) -> Personality:
    """Apply the edit form to one persona.

    Raises ``KeyError`` when the slug is unknown and ``pydantic.ValidationError``
    when the form does not hold — the route turns those into 404 and 422.
    ``ValueError`` is a bad ``style`` or ``look`` from the simple picker.
    """
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
    with closing(_connect(settings)) as conn, conn:
        conn.execute(_INSERT, _params(stored))
    return stored


def create(settings: Any, payload: dict[str, Any] | None) -> Personality:
    """A new persona from the simple form: a name, how they talk, a look."""
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
    with closing(_connect(settings)) as conn, conn:
        conn.execute(_INSERT, _params(person))
    return person


def activate(settings: Any, slug: str) -> Personality:
    """Put one persona on the phone and take every other one off it.

    One transaction: the clinic is never left with two receptionists or none.
    """
    now = _now()
    with closing(_connect(settings)) as conn, conn:
        if conn.execute("SELECT 1 FROM personalities WHERE slug = ?", (slug,)).fetchone() is None:
            raise KeyError(slug)
        conn.execute(
            "UPDATE personalities SET active = 0, updated_at = ? WHERE active = 1 AND slug != ?",
            (now, slug),
        )
        conn.execute(
            "UPDATE personalities SET active = 1, updated_at = ? WHERE slug = ?", (now, slug)
        )
        row = conn.execute("SELECT * FROM personalities WHERE slug = ?", (slug,)).fetchone()
    return _from_row(row)
