"""Clinic vocabulary handed to the STT so it spells our nouns right.

Owner: the conversation lane.

Soniox ``stt-rt-v5`` takes a context object and biases recognition towards the
terms in it. On an 8 kHz phone line that is the difference between "Dra. Sáenz"
and "Dra. Sáez" — the near-miss surnames the clinic deliberately has.

The list is built per call, from the catalogue the clinic client already holds.
It is read from the cache only: this runs while the pipeline is being wired and
must never block on the network, and must never raise. Soniox caps the whole
context object at 8k tokens, so keep it to proper nouns.
"""

from __future__ import annotations

from typing import Any

from vortex.clinic import fixtures
from vortex.conversation.prompt import CLINIC_NAME

# Said on every call, in the language the caller uses. Not in the catalogue.
# English first (the clinic's default), then the Spanish and Catalan the
# exceptions use. Soniox spells a boosted term the way it is written here.
SPOKEN_TERMS: tuple[str, ...] = (
    CLINIC_NAME,
    "Arenal Centro",
    "Arenal Norte",
    "Arenal Sur",
    "Getafe",
    "appointment",
    "General Practice",
    "Paediatrics",
    "Dermatology",
    "Orthopaedics",
    "Gynaecology",
    "Physiotherapy",
    "referral",
    "insurer",
    "Sanitas",
    "Adeslas",
    "ASISA",
    "DKV",
    "Mapfre",
    "AXA",
    "Cigna",
    "cita previa",
    "medicina general",
    "pediatría",
    "dermatología",
    "traumatología",
    "ginecología",
    "fisioterapia",
    "volante",
    "derivación",
    "mutua",
    "seguro",
    "número de historia",
    "DNI",
    "NIE",
)

MAX_TERMS = 200


def _cached_catalogue(clinic: Any) -> Any | None:
    """The catalogue the client already has, or None. Never fetches."""
    return getattr(clinic, "_catalogue", None)


def _catalogue_terms(catalogue: Any) -> list[str]:
    terms: list[str] = []
    for group, attr in (
        ("providers", "name"),
        ("locations", "name"),
        ("specialties", "name"),
        ("insurance_plans", "name"),
    ):
        for record in getattr(catalogue, group, None) or []:
            value = getattr(record, attr, None)
            if isinstance(value, str) and value.strip():
                terms.append(value.strip())
    return terms


def _fallback_terms() -> list[str]:
    """The offline fixtures, for a live client that has not fetched yet."""
    terms: list[str] = []
    for group in (fixtures.PROVIDERS, fixtures.LOCATIONS, fixtures.SPECIALTIES):
        for record in group:
            name = record.get("name")
            if isinstance(name, str) and name.strip():
                terms.append(name.strip())
    return terms


# Free-text context for Soniox (up to 8k tokens). The shape of a Spanish
# national id and the check alphabet bias digit and letter recognition; the
# letters I, O, U and Ñ never occur, which the identity lane also enforces.
# English, because that is the language of most calls; the Spanish sentence
# at the end covers the callers who switch.
STT_CONTEXT_TEXT = (
    "Phone call to the reception desk of a private clinic in Madrid, Spain, to "
    "book, move or cancel a medical appointment. Most callers speak English; "
    "some speak Spanish or Catalan. The caller gives their name, two surnames, "
    "date of birth, phone number and their DNI or NIE. A DNI is eight digits "
    "followed by a check letter; a NIE starts with X, Y or Z, then seven digits "
    "and a letter. Possible check letters: T R W A G M Y F P D X B N J Z S Q V H "
    "L C K E. Digits are often read out one at a time or in pairs. "
    "Llamada a la recepción de una clínica para pedir, cambiar o anular una cita; "
    "el paciente dice su nombre, apellidos, fecha de nacimiento, teléfono y DNI o NIE."
)


def stt_context_text() -> str:
    return STT_CONTEXT_TEXT


def stt_terms(ctx: Any) -> list[str]:
    """Clinic vocabulary to boost, deduplicated and order-stable. Never raises."""
    terms = list(SPOKEN_TERMS)
    try:
        catalogue = _cached_catalogue(getattr(ctx, "clinic", None))
        terms += _catalogue_terms(catalogue) if catalogue is not None else _fallback_terms()
    except Exception:  # a bad catalogue must not cost us the call
        pass
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            unique.append(term)
    return unique[:MAX_TERMS]
