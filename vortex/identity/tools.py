"""identity/ tools - who is calling.

Owner: the identity lane. Signatures are frozen in ``vortex/contract.py``.

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
  counts as 0/1/2. A wrong letter is a 422 at submit time. When the letter
  does not match, a unique 1-edit digit repair (spoken confusions) is kept;
  several repairs mean re-ask those digit positions.

How the conversation should read what comes back:

- ``FindPatientResult.status == "ambiguous"``: ask for ``ask_for``; it is the
  first unfilled field that actually tells the candidates apart.
- ``status == "not_found"`` with ``candidates``: the exact query found nobody,
  but dropping the field most often misheard (the id, then the phone) found
  these near misses. They are a prompt to ask the caller to repeat that field.
  Never book one of them without a fresh exact lookup.
- ``RegistrationResult.rejection``: the record cannot be submitted as dictated.
  ``detail`` starts with the field to ask again (``national_id: ...``,
  ``insurer: ...``). It is an "ask again" signal, not a reason to end the call.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from datetime import date
from typing import Any

from vortex.contract import (
    Appointment,
    BuildRegistrationInput,
    CallerLineMatch,
    Catalogue,
    FindPatientInput,
    FindPatientResult,
    NationalIdCheck,
    PatientRecord,
    RegisterAction,
    RegistrationResult,
    Rejection,
    ToolContext,
    ValidateNationalIdInput,
    remember_patient,
)
from vortex.identity.dictation import check_email, check_phone, spoken_email

_CHECK_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
_NIE_PREFIX_DIGIT = {"X": "0", "Y": "1", "Z": "2"}
_DNI_RE = re.compile(r"\d{8}[A-Z]")
_NIE_RE = re.compile(r"[XYZ]\d{7}[A-Z]")
_ID_SEPARATORS = re.compile(r"[\s.\-]+")
_NON_DIGIT = re.compile(r"\D")
_WS = re.compile(r"\s+")

#: Spoken digit confusions (STT under noise): seis/siete, ocho/cero, uno/siete,
#: cinco/seis, seis/tres. One substitution only — two edits produce false
#: positives (docs/research/05-structured-data.md).
_DIGIT_CONFUSIONS: dict[str, tuple[str, ...]] = {
    "0": ("8",),
    "1": ("7",),
    "3": ("6",),
    "5": ("6",),
    "6": ("7", "3"),
    "7": ("6",),
    "8": ("0",),
}

#: The ``insurer`` enum the register route accepts (docs/api/openapi.json). The
#: live catalogue lists the same plans; the offline fixtures list only five, so
#: the union keeps offline behaviour identical to the platform's.
KNOWN_INSURERS: tuple[str, ...] = (
    "sanitas",
    "adeslas",
    "dkv",
    "asisa",
    "mapfre",
    "caser",
    "cigna",
    "axa",
    "nueva_mutua",
    "privado",
)

#: Spoken forms that do not fold to a plan id or name by themselves.
_INSURER_ALIASES: dict[str, str] = {
    "mapfre salud": "mapfre",
    "mapfre health": "mapfre",
    "nueva mutua": "nueva_mutua",
    "nueva mutua sanitaria": "nueva_mutua",
    "axa health": "axa",
    "axa salud": "axa",
    "cigna health": "cigna",
    "caser salud": "caser",
    "private": "privado",
    "privately": "privado",
    "paying privately": "privado",
    "self pay": "privado",
    "self-pay": "privado",
    "no insurance": "privado",
    "none": "privado",
    "particular": "privado",
    "sin seguro": "privado",
    "privat": "privado",
}

PATIENT_POSTPROCESS_KEY = "patient_postprocess"
PATIENT_PREFERENCES_KEY = "patient_preferences"
IDENTITY_KEY = "identity"
#: The first patient identified this call. Unlike IDENTITY_KEY, never
#: overwritten by a later lookup, so a third-party booking (problem 9) can
#: still tell who was on the line to begin with.
CALLER_IDENTITY_KEY = "identity_caller"
_MIN_SUPPORT = 2  # occurrences needed before a pattern is worth suggesting
_MAX_NEAR_MISSES = 3  # more than this and a near-miss list is noise, not a hint

# Fire-and-forget tasks need a strong reference until they finish, or the event
# loop may drop them half-way. This holds nothing a call can read; it is not
# shared state between calls, only garbage-collection insurance.
_background: set[asyncio.Task[Any]] = set()


# ---------------------------------------------------------------------------
# National id
# ---------------------------------------------------------------------------


def normalize_national_id(value: str) -> str:
    """As dictated -> the platform's shape: no spaces, dots or dashes, uppercase."""
    return _ID_SEPARATORS.sub("", value.strip()).upper()


def _check_letter(digits8: str) -> str:
    return _CHECK_LETTERS[int(digits8) % 23]


def _one_edit_bodies(body: str) -> list[str]:
    """Every 1-substitution of ``body`` under the spoken-digit confusion map."""
    out: list[str] = []
    for index, digit in enumerate(body):
        for alt in _DIGIT_CONFUSIONS.get(digit, ()):
            out.append(body[:index] + alt + body[index + 1 :])
    return out


def _ambiguous_positions(bodies: list[str]) -> list[int]:
    """Digit indexes that are not unanimous across matching 1-edit bodies."""
    if not bodies:
        return []
    length = len(bodies[0])
    return [i for i in range(length) if len({body[i] for body in bodies}) > 1]


def check_national_id(value: str) -> NationalIdCheck:
    """Normalise, classify, re-derive the letter; repair a unique 1-edit mishear.

    When the heard letter does not match the digits, try every single-digit
    confusion (seis/tres, seis/siete, …). Keep the repair only when exactly one
    candidate's check letter matches the heard letter. Several matches →
    ``ask_digit_positions`` names the digits to re-ask; zero → leave invalid.
    """
    normalized = normalize_national_id(value)
    if _DNI_RE.fullmatch(normalized):
        body, letter, kind = normalized[:8], normalized[8], "dni"
        prefix: str | None = None
    elif _NIE_RE.fullmatch(normalized):
        prefix, body, letter = normalized[0], normalized[1:8], normalized[8]
        kind = "nie"
    else:
        return NationalIdCheck(normalized=normalized, kind="invalid", valid=False)

    digits8 = body if prefix is None else _NIE_PREFIX_DIGIT[prefix] + body
    expected = _check_letter(digits8)
    if letter == expected:
        return NationalIdCheck(
            normalized=normalized, kind=kind, valid=True, expected_letter=expected
        )

    matching_bodies: list[str] = []
    for edited in _one_edit_bodies(body):
        candidate_digits = edited if prefix is None else _NIE_PREFIX_DIGIT[prefix] + edited
        if _check_letter(candidate_digits) == letter:
            matching_bodies.append(edited)
    unique_bodies = list(dict.fromkeys(matching_bodies))

    if len(unique_bodies) == 1:
        repaired_body = unique_bodies[0]
        repaired = repaired_body + letter if prefix is None else prefix + repaired_body + letter
        return NationalIdCheck(
            normalized=repaired,
            kind=kind,
            valid=True,
            expected_letter=letter,
            repaired_from=normalized,
        )

    if len(unique_bodies) > 1:
        return NationalIdCheck(
            normalized=normalized,
            kind=kind,
            valid=False,
            expected_letter=expected,
            ask_digit_positions=_ambiguous_positions(unique_bodies),
        )

    return NationalIdCheck(normalized=normalized, kind=kind, valid=False, expected_letter=expected)


async def validate_national_id(ctx: ToolContext, args: ValidateNationalIdInput) -> NationalIdCheck:
    """Normalise a spoken DNI/NIE and check its letter (mod-23), with 1-edit repair."""
    return check_national_id(args.value)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def _fold(text: str) -> str:
    """NFKD, strip combining marks, casefold, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _WS.sub(" ", stripped).strip().casefold()


def normalize_phone(phone: str) -> str:
    """As dictated -> E.164 via ``phonenumbers`` (region ES). Digits and spoken
    forms both work; a bare nine-digit Spanish number gets ``+34``.
    """
    return check_phone(phone).normalized


def normalize_email(email: str) -> str:
    """As dictated -> an address. ``ana punto garcia arroba gmail punto com`` ->
    ``ana.garcia@gmail.com``. Uses the spoken mapper in ``dictation``; syntax is
    checked separately by ``check_email`` / ``build_registration``.
    """
    return spoken_email(email)


def resolve_insurer(spoken: str, catalogue: Catalogue | None = None) -> str | None:
    """The plan id for what the caller said, or ``None`` when no plan matches.

    Matches, after folding case and accents: a plan id, a plan name from the
    catalogue, a known alias ("Mapfre Salud", "paying privately"), and finally a
    plan id spoken as the first word ("Cigna Global" -> ``cigna``).
    """
    text = _fold(spoken).replace("_", " ")
    if not text:
        return None
    ids: dict[str, str] = {}
    for plan_id in KNOWN_INSURERS:
        ids[plan_id.replace("_", " ")] = plan_id
    if catalogue is not None:
        for plan in catalogue.insurance_plans:
            ids[plan.insurer_id.replace("_", " ")] = plan.insurer_id
            ids[_fold(plan.name)] = plan.insurer_id
    if text in ids:
        return ids[text]
    if text in _INSURER_ALIASES:
        return _INSURER_ALIASES[text]
    first_word = text.split(" ")[0]
    if first_word in ids and " " not in ids[first_word]:
        return ids[first_word]
    return None


def _person_field(value: str) -> str:
    return _WS.sub(" ", value).strip()


async def build_registration(ctx: ToolContext, args: BuildRegistrationInput) -> RegistrationResult:
    """Turn dictated demographics into a ``RegisterAction``, or say which field to ask again.

    The id's check letter is re-derived here because the platform re-derives it
    at submit time and a mismatch is a 422: better to ask the caller to repeat
    the id than to post a record that cannot be accepted. The insurer is folded
    to the plan id the register route's enum accepts.

    An empty ``phone`` means the line they are calling from, which Twilio hands
    us before the greeting. A new patient registers themselves, so the number
    they would dictate is the number they dialled from - it was identical on
    every registration the platform has accepted from us - and a registration
    has eight fields to collect inside a three-minute call. Asking for the one
    field we already hold is a round trip that costs the whole case. With no
    caller id there is nothing to fall back on and the refusal below still names
    ``phone`` for the caller to dictate.
    """

    def ask_again(field_name: str, why: str) -> RegistrationResult:
        return Rejection(reason="out_of_scope", detail=f"{field_name}: {why}")

    check = check_national_id(args.national_id)
    if check.kind == "invalid":
        rejection = ask_again(
            "national_id",
            f"{check.normalized!r} is neither a DNI (8 digits + letter) nor a NIE "
            "(X/Y/Z + 7 digits + letter); ask the caller to repeat it",
        )
        return RegistrationResult(rejection=rejection)
    if not check.valid:
        if check.ask_digit_positions:
            pair = ", ".join(str(i + 1) for i in check.ask_digit_positions)
            rejection = ask_again(
                "national_id",
                f"check letter of {check.normalized} matches more than one 1-edit "
                f"reading of the digits; ask the caller to repeat digit positions "
                f"{pair} (1-based in the digit body)",
            )
        else:
            rejection = ask_again(
                "national_id",
                f"check letter of {check.normalized} does not match its digits "
                f"(they give {check.expected_letter}); a digit was misheard, ask again",
            )
        return RegistrationResult(rejection=rejection)

    try:
        catalogue = await ctx.clinic.catalogue()
    except Exception as exc:  # the enum is known; the catalogue only adds names
        ctx.log.event("identity.catalogue_unavailable", detail=f"{type(exc).__name__}: {exc}")
        catalogue = None
    insurer = resolve_insurer(args.insurer, catalogue)
    if insurer is None:
        rejection = ask_again(
            "insurer",
            f"{args.insurer!r} is not a plan the clinic registers "
            f"({', '.join(KNOWN_INSURERS)}); ask which insurer, or whether they pay privately",
        )
        return RegistrationResult(rejection=rejection)

    given = _person_field(args.given_name)
    first = _person_field(args.first_surname)
    second = _person_field(args.second_surname)
    for field_name, value in (
        ("given_name", given),
        ("first_surname", first),
        ("second_surname", second),
    ):
        if not value:
            return RegistrationResult(
                rejection=ask_again(field_name, "is empty; the record needs two surnames")
            )

    email_check = check_email(args.email)
    if not email_check.valid:
        return RegistrationResult(
            rejection=ask_again(
                "email",
                f"{email_check.normalized!r} is not an address"
                + (f" ({email_check.detail})" if email_check.detail else "")
                + "; read it back and ask again",
            )
        )

    phone_check = check_phone(args.phone or ctx.from_number)
    if not phone_check.possible:
        return RegistrationResult(
            rejection=ask_again(
                "phone",
                f"{args.phone!r} is not a Spanish number"
                + (f" ({phone_check.detail})" if phone_check.detail else "")
                + "; ask the caller to repeat it",
            )
        )

    return RegistrationResult(
        action=RegisterAction(
            given_name=given,
            first_surname=first,
            second_surname=second,
            national_id=check.normalized,
            date_of_birth=args.date_of_birth,
            phone=phone_check.normalized,
            email=email_check.normalized,
            insurer=insurer,
        )
    )


# ---------------------------------------------------------------------------
# Directory lookup
# ---------------------------------------------------------------------------


def _unanimous(values: list[str]) -> str | None:
    """The one value every item shares, if there are enough of them to call it a pattern."""
    return values[0] if len(values) >= _MIN_SUPPORT and len(set(values)) == 1 else None


def _mine_preferences(history: list[Appointment]) -> dict[str, Any]:
    """Patterns in past visits: where/who they always went to, per appointment type too.

    Not a rejection or a rule: a set of soft defaults the conversation can offer
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


async def _postprocess_patient(ctx: ToolContext, patient: PatientRecord) -> None:
    """Background work kicked off the moment a caller is identified.

    Writes the mined preferences to ``ctx.state[PATIENT_PREFERENCES_KEY]`` when
    done. Never raises: nothing on the happy path awaits this task, so an
    unhandled exception would only surface as an asyncio "exception never
    retrieved" warning, silently.
    """
    try:
        history = await ctx.clinic.appointments(patient.patient_id, when="past")
        ctx.state[PATIENT_PREFERENCES_KEY] = {
            "patient_id": patient.patient_id,
            **_mine_preferences(history),
        }
    except Exception as exc:
        ctx.log.event("patient_postprocess.failed", detail=f"{type(exc).__name__}: {exc}")


def _start_postprocess(ctx: ToolContext, patient: PatientRecord) -> None:
    task = asyncio.create_task(_postprocess_patient(ctx, patient))
    _background.add(task)
    task.add_done_callback(_background.discard)


def _digits9(phone: str) -> str:
    return _NON_DIGIT.sub("", phone)[-9:]


def _fields_given(args: FindPatientInput) -> list[str]:
    return [
        name
        for name, value in (
            ("name", args.name),
            ("national_id", args.national_id),
            ("phone", args.phone),
            ("date_of_birth", args.date_of_birth),
        )
        if value
    ]


def _splitting_field(args: FindPatientInput, candidates: list[PatientRecord]) -> str:
    """The first unfilled field whose values differ across the candidates.

    date_of_birth is the go-to disambiguator: it is what the docs recommend and
    the one thing a caller always knows. name is last since it is already given.
    """
    values: dict[str, list[Any]] = {
        "date_of_birth": [p.date_of_birth for p in candidates],
        "national_id": [normalize_national_id(p.national_id) for p in candidates],
        "phone": [_digits9(p.phone) for p in candidates],
        "name": [_fold(p.full_name) for p in candidates],
    }
    given = {
        "date_of_birth": args.date_of_birth,
        "national_id": args.national_id,
        "phone": args.phone,
        "name": args.name,
    }
    for field_name in ("date_of_birth", "national_id", "phone", "name"):
        if given[field_name]:
            continue
        seen = [v for v in values[field_name] if v]
        if len(set(seen)) > 1:
            return field_name
    for field_name in ("date_of_birth", "national_id", "phone", "name"):
        if not given[field_name]:
            return field_name
    return ""


def _line_owner_first(ctx: ToolContext, candidates: list[PatientRecord]) -> list[PatientRecord]:
    """Order candidates so the owner of the calling line comes first. A hint, not a pick."""
    if not ctx.from_number:
        return candidates
    line = _digits9(ctx.from_number)
    return sorted(candidates, key=lambda p: 0 if p.phone and _digits9(p.phone) == line else 1)


async def _lookup(
    ctx: ToolContext,
    *,
    name: str | None,
    national_id: str | None,
    phone: str | None,
    date_of_birth: date | None,
) -> list[PatientRecord]:
    """Every ``/directory`` query this lane makes, and the one place they land.

    Whatever comes back is kept on the context: ``/directory`` has no lookup by
    id, so this is the only way another lane holding a bare ``patient_id`` (the
    rules lane, checking age and referrals) can get at the record.
    """
    found = await ctx.clinic.directory(
        name=name, national_id=national_id, phone=phone, date_of_birth=date_of_birth
    )
    for record in found:
        remember_patient(ctx, record)
    return found


async def find_patient(ctx: ToolContext, args: FindPatientInput) -> FindPatientResult:
    """Look the caller up in /directory and decide: found, ambiguous or not_found.

    Every field given is an exact filter: one that does not match excludes the
    patient. When nothing is given the calling line is searched instead, which
    finds the line's owner, not necessarily the patient being booked for.
    """
    name = _person_field(args.name) if args.name else None
    if args.national_id:
        id_check = check_national_id(args.national_id)
        national_id = (
            id_check.normalized if id_check.valid else normalize_national_id(args.national_id)
        )
    else:
        national_id = None
    phone = args.phone.strip() if args.phone else None
    dob = args.date_of_birth
    given = _fields_given(args)
    if not given:
        # Caller gave nothing to search on: fall back to the line's own number.
        phone = ctx.from_number
        if not phone:
            return FindPatientResult(status="not_found")

    candidates = await _lookup(
        ctx, name=name, national_id=national_id, phone=phone, date_of_birth=dob
    )

    if len(candidates) == 1:
        patient = candidates[0]
        entry = {
            "patient_id": patient.patient_id,
            "matched_on": given or ["from_number"],
        }
        ctx.state.setdefault(CALLER_IDENTITY_KEY, entry)
        ctx.state[IDENTITY_KEY] = entry
        # Mine their visit history while the conversation carries on, so a
        # preference is already there by the time it is needed.
        _start_postprocess(ctx, patient)
        return FindPatientResult(status="found", patient=patient)

    if candidates:
        ordered = _line_owner_first(ctx, candidates)
        return FindPatientResult(
            status="ambiguous", candidates=ordered, ask_for=_splitting_field(args, ordered)
        )

    # Nobody matched every field. The id and the phone are the fields most
    # often misheard: drop the one given and see who the rest of the query
    # finds, so the conversation can ask for that field again with a name in
    # hand. These are near misses, never an identification.
    near: list[PatientRecord] = []
    if len(given) >= 2:
        for dropped in ("national_id", "phone"):
            if dropped not in given:
                continue
            near = await _lookup(
                ctx,
                name=name,
                national_id=None if dropped == "national_id" else national_id,
                phone=None if dropped == "phone" else phone,
                date_of_birth=dob,
            )
            if near:
                break
    if near and len(near) <= _MAX_NEAR_MISSES:
        ctx.log.event(
            "identity.near_miss",
            given=given,
            candidates=[p.patient_id for p in near],
        )
        return FindPatientResult(status="not_found", candidates=_line_owner_first(ctx, near))
    return FindPatientResult(status="not_found")


async def resolve_caller_line(ctx: ToolContext) -> CallerLineMatch:
    """Who the dialling line belongs to, asked before the caller has spoken.

    The scored runs lose calls to the clock, and the largest single block of it
    is the opening exchange: the name, then a second identifier, one field per
    turn, against a caller who hesitates. Twilio hands us the number on the
    ``start`` message and ``/directory`` accepts a phone on its own, so that
    exchange is answerable for free before the greeting is spoken.

    One match is the line's owner. No match means the line is on no record,
    which is the new-patient signal. Several means a shared line and names
    nobody, though the records still go back so ``find_patient`` can order them.

    Never raises: a call that cannot look its line up is a call that asks the
    caller instead, exactly as before.
    """
    from_number = ctx.from_number or ""
    if not from_number:
        return CallerLineMatch()
    try:
        candidates = await _lookup(
            ctx, name=None, national_id=None, phone=from_number, date_of_birth=None
        )
    except Exception as exc:
        ctx.log.event("identity.caller_line_failed", detail=f"{type(exc).__name__}: {exc}")
        return CallerLineMatch()

    match = CallerLineMatch(
        looked_up=True,
        from_number=from_number,
        patient=candidates[0] if len(candidates) == 1 else None,
        candidates=candidates,
    )
    if match.patient is not None:
        # The same bookkeeping ``find_patient`` does for a single match, so a
        # later third-party booking still knows who was on the line, and the
        # visit history is mined while the greeting plays.
        entry = {"patient_id": match.patient.patient_id, "matched_on": ["from_number"]}
        ctx.state.setdefault(CALLER_IDENTITY_KEY, entry)
        _start_postprocess(ctx, match.patient)
    ctx.log.event(
        "identity.caller_line",
        matches=len(candidates),
        patient_id=match.patient.patient_id if match.patient else "",
    )
    return match


def note_target_patient(ctx: ToolContext, target_patient_id: str) -> None:
    """Log when a booking or cancellation names someone other than whoever this
    call first identified (problem 9: the third party).

    Not a guard: a parent booking for a child, or a carer for someone they look
    after, is the correct outcome, never a failure to prevent. This only leaves
    a trace on divergence, so the case is visible in the call log rather than
    silent either way.
    """
    caller = ctx.state.get(CALLER_IDENTITY_KEY)
    if caller and caller["patient_id"] != target_patient_id:
        ctx.log.event(
            "identity.third_party",
            caller_patient_id=caller["patient_id"],
            target_patient_id=target_patient_id,
        )
