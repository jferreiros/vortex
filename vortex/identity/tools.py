"""identity/ tools - who is calling.

Owner: the identity lane. Replace each ``stub_*`` call with the real logic.
Keep the signatures exactly as ``vortex/contract.py`` declares them.

What the docs say this lane must get right (clinic docs, "Six things worth knowing"):

- /directory filters on exact fields. A field that does not match excludes the
  patient. Use name + date_of_birth to split two people with the same name.
- Confirm on a second field before you trust a match.
- Submit the record's name and ids, never what the caller said.
- ``from_number`` is a hint, never identification. The caller is not always
  the patient (a parent for a child, a daughter for her father).
- A caller the directory does not know cannot be booked. Register first.
- DNI: 8 digits + letter. NIE: X/Y/Z + 7 digits + letter. The letter is
  ``"TRWAGMYFPDXBNJZSQVHLCKE"[number % 23]`` where a NIE's leading X/Y/Z
  counts as 0/1/2. A wrong letter is a 422 at submit time.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from vortex.contract import (
    Appointment,
    BuildRegistrationInput,
    FindPatientInput,
    FindPatientResult,
    NationalIdCheck,
    PatientRecord,
    RegisterAction,
    RegistrationResult,
    ToolContext,
    ValidateNationalIdInput,
)

_CHECK_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
_NIE_PREFIX_DIGIT = {"X": "0", "Y": "1", "Z": "2"}
_DNI_RE = re.compile(r"\d{8}[A-Z]")
_NIE_RE = re.compile(r"[XYZ]\d{7}[A-Z]")

PATIENT_POSTPROCESS_KEY = "patient_postprocess"
_MIN_SUPPORT = 2  # occurrences needed before a pattern is worth suggesting


def _unanimous(values: list[str]) -> str | None:
    """The one value every item shares, if there are enough of them to call it a pattern."""
    return values[0] if len(values) >= _MIN_SUPPORT and len(set(values)) == 1 else None


def _mine_preferences(history: list[Appointment]) -> dict[str, Any]:
    """Patterns in past visits: where/who they always went to, per appointment type too.

    Not a rejection or a rule — a set of soft defaults the conversation can offer
    ("you're usually at Sur, want that again?") instead of asking cold.
    """
    locations = [a.location_id for a in history]
    providers = [a.provider_id for a in history]
    by_type: dict[str, list[Appointment]] = {}
    for a in history:
        by_type.setdefault(a.appointment_type_id, []).append(a)

    return {
        "visit_count": len(history),
        "location_preference": _unanimous(locations),
        "distinct_locations": sorted(set(locations)),
        "provider_preference": _unanimous(providers),
        "distinct_providers": sorted(set(providers)),
        "type_provider_preference": {
            t: p
            for t, items in by_type.items()
            if (p := _unanimous([a.provider_id for a in items]))
        },
        "type_location_preference": {
            t: loc
            for t, items in by_type.items()
            if (loc := _unanimous([a.location_id for a in items]))
        },
    }


async def _postprocess_patient(ctx: ToolContext, patient: PatientRecord) -> dict[str, Any]:
    """Background work kicked off the moment a caller is identified.

    Never raises: nothing on the happy path ever awaits this task, so an
    unhandled exception would otherwise only surface as an asyncio "exception
    never retrieved" warning, silently.
    """
    try:
        history = await ctx.clinic.appointments(patient.patient_id, when="past")
        return _mine_preferences(history)
    except Exception as exc:
        ctx.log.event("patient_postprocess.failed", detail=f"{type(exc).__name__}: {exc}")
        return {}


async def find_patient(ctx: ToolContext, args: FindPatientInput) -> FindPatientResult:
    """Look the caller up in /directory and decide: found, ambiguous or not_found."""
    phone = args.phone
    gave_nothing = not any((args.name, args.national_id, args.phone, args.date_of_birth))
    if gave_nothing:
        # Caller gave nothing else to search on: fall back to the line's own number.
        phone = ctx.from_number

    candidates = await ctx.clinic.directory(
        name=args.name, national_id=args.national_id, phone=phone, date_of_birth=args.date_of_birth
    )
    if not candidates:
        return FindPatientResult(status="not_found")
    if len(candidates) == 1:
        patient = candidates[0]
        # Fire-and-forget: mine their visit history while the conversation carries
        # on, so a preference is already there by the time it's needed.
        ctx.state[PATIENT_POSTPROCESS_KEY] = asyncio.create_task(
            _postprocess_patient(ctx, patient)
        )
        return FindPatientResult(status="found", patient=patient)

    # Ambiguous: ask for whichever unfilled field would split the candidates.
    # date_of_birth is the go-to disambiguator; name is last since it's already given.
    for field_name, given in (
        ("date_of_birth", args.date_of_birth),
        ("national_id", args.national_id),
        ("phone", args.phone),
        ("name", args.name),
    ):
        if given is None:
            return FindPatientResult(status="ambiguous", candidates=candidates, ask_for=field_name)
    return FindPatientResult(status="ambiguous", candidates=candidates)


async def validate_national_id(ctx: ToolContext, args: ValidateNationalIdInput) -> NationalIdCheck:
    """Normalise a spoken DNI/NIE and check its letter (mod-23)."""
    normalized = args.value.strip().upper().replace(" ", "").replace("-", "")
    if _DNI_RE.fullmatch(normalized):
        digits, letter, kind = normalized[:8], normalized[8], "dni"
    elif _NIE_RE.fullmatch(normalized):
        digits = _NIE_PREFIX_DIGIT[normalized[0]] + normalized[1:8]
        letter, kind = normalized[8], "nie"
    else:
        return NationalIdCheck(normalized=normalized, kind="invalid", valid=False)
    expected = _CHECK_LETTERS[int(digits) % 23]
    return NationalIdCheck(
        normalized=normalized, kind=kind, valid=letter == expected, expected_letter=expected
    )


def _normalize_phone(phone: str) -> str:
    """As dictated -> E.164. A bare 9-digit Spanish number gets the +34 prefix."""
    had_plus = phone.strip().startswith("+")
    digits = "".join(ch for ch in phone if ch.isdigit())
    if had_plus:
        return f"+{digits}"
    if len(digits) == 9:
        return f"+34{digits}"
    return digits


async def build_registration(ctx: ToolContext, args: BuildRegistrationInput) -> RegistrationResult:
    """Turn dictated demographics into a ``RegisterAction``.

    The national id's check letter is not re-validated here: the conversation
    is expected to have already confirmed it with ``validate_national_id``
    (asking the caller to repeat a wrong digit) before demographics are
    complete enough to call this. A malformed id still 422s at submit time.
    """
    check = await validate_national_id(ctx, ValidateNationalIdInput(value=args.national_id))
    return RegistrationResult(
        action=RegisterAction(
            given_name=args.given_name,
            first_surname=args.first_surname,
            second_surname=args.second_surname,
            national_id=check.normalized,
            date_of_birth=args.date_of_birth,
            phone=_normalize_phone(args.phone),
            email=args.email.strip().lower(),
            insurer=args.insurer,
        )
    )
