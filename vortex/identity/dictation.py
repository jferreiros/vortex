"""identity/dictation - spoken forms of an email and a phone -> the exact string.

Problem 4 registers a new patient and one wrong character fails the case. The
transcript never carries the characters: it carries "ana punto garcia arroba
gmail punto com" in Spanish, "ana punt garcia arrova gmail punt com" in Catalan,
"ana dot garcia at gmail dot com" in English, and a mobile as "seis uno dos ...".
This module turns those into ``ana.garcia@gmail.com`` and ``+34612345678`` and
says, typed, whether the result can be submitted.

Libraries (docs/research/05-structured-data.md, section 3):

- ``email-validator`` checks the syntax. DNS is never consulted: a call has three
  minutes and the scorer compares strings, not mailboxes.
- ``phonenumbers`` parses with region ``ES`` and formats E.164. The gate is
  ``is_possible_number`` (right length for the country), not ``is_valid_number``:
  the organisers' own cases use 7xx mobiles the metadata does not list as
  allocated, and refusing those would fail the case the tool exists to pass.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

import phonenumbers
from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel

_WS = re.compile(r"\s+")
_NON_DIGIT = re.compile(r"\D")

#: Spoken punctuation, es / ca / en. Longest phrase first so "guion bajo" wins
#: over "guion" and "at sign" over "at". Accents are folded before matching,
#: so "guión" and "guió" arrive as "guion" and "guio".
EMAIL_SPOKEN: tuple[tuple[str, str], ...] = (
    ("guion bajo", "_"),
    ("guio baix", "_"),
    ("barra baja", "_"),
    ("subrayado", "_"),
    ("subratllat", "_"),
    ("underscore", "_"),
    ("at sign", "@"),
    ("at symbol", "@"),
    ("arroba", "@"),
    ("arrova", "@"),
    ("at", "@"),
    ("punto", "."),
    ("punt", "."),
    ("dot", "."),
    ("period", "."),
    ("guion medio", "-"),
    ("guionet", "-"),
    ("guion", "-"),
    ("guio", "-"),
    ("hyphen", "-"),
    ("dash", "-"),
    ("minus", "-"),
    ("menos", "-"),
)

#: Things a caller says about the address that are not part of it.
_EMAIL_FILLER: tuple[str, ...] = (
    "todo junto",
    "todo en minusculas",
    "todo en minuscula",
    "en minusculas",
    "en minuscula",
    "sin espacios",
    "tot junt",
    "tot en minuscules",
    "en minuscules",
    "sense espais",
    "all one word",
    "all together",
    "all lowercase",
    "in lowercase",
    "lowercase",
    "no spaces",
)

#: Domain names as an 8 kHz line and a Spanish speaker render them.
_DOMAIN_ALIASES: dict[str, str] = {
    "jotmail": "hotmail",
    "jotmeil": "hotmail",
    "otmail": "hotmail",
    "hotmeil": "hotmail",
    "yimeil": "gmail",
    "yimail": "gmail",
    "jimeil": "gmail",
    "gmeil": "gmail",
    "yahu": "yahoo",
    "yaju": "yahoo",
    "aiclaud": "icloud",
    "aicloud": "icloud",
    "autluk": "outlook",
    "outluk": "outlook",
    "autlook": "outlook",
}

#: Single digits as words, es / ca / en. Single letters ("u", "o") stay out:
#: a caller spelling an address letter by letter must not gain a digit.
DIGIT_WORDS: dict[str, str] = {
    "cero": "0",
    "zero": "0",
    "uno": "1",
    "un": "1",
    "one": "1",
    "dos": "2",
    "two": "2",
    "tres": "3",
    "three": "3",
    "cuatro": "4",
    "quatre": "4",
    "four": "4",
    "cinco": "5",
    "cinc": "5",
    "five": "5",
    "seis": "6",
    "sis": "6",
    "six": "6",
    "siete": "7",
    "set": "7",
    "seven": "7",
    "ocho": "8",
    "vuit": "8",
    "eight": "8",
    "nueve": "9",
    "nou": "9",
    "nine": "9",
}

#: Spoken forms of the international prefix, folded.
_PHONE_PREFIX_WORDS: tuple[str, ...] = ("mas", "mes", "plus", "prefijo", "prefix")


class EmailCheck(BaseModel):
    """What the dictation became and whether it is an address."""

    normalized: str
    valid: bool
    detail: str = ""


class PhoneCheck(BaseModel):
    """What the dictation became and whether the platform can take it.

    ``possible`` is the submit gate: the right number of digits for the region.
    ``valid`` is stricter (an allocated range) and only informs the log.
    """

    normalized: str
    possible: bool
    valid: bool
    kind: Literal["mobile", "fixed_line", "other", "invalid"] = "invalid"
    detail: str = ""


def _fold(text: str) -> str:
    """NFKD, strip combining marks, casefold, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _WS.sub(" ", stripped).strip().casefold()


def _replace_word(text: str, spoken: str, symbol: str) -> str:
    """Replace ``spoken`` where it stands as its own word. ``at`` never touches ``matias``."""
    return re.sub(rf"(?<![a-z0-9]){re.escape(spoken)}(?![a-z0-9])", symbol, text)


def _digit_words(text: str) -> str:
    return " ".join(DIGIT_WORDS.get(word, word) for word in text.split(" "))


def _alias_domain(address: str) -> str:
    local, at, domain = address.rpartition("@")
    if not at:
        return address
    labels = domain.split(".")
    labels[0] = _DOMAIN_ALIASES.get(labels[0], labels[0])
    return f"{local}@{'.'.join(labels)}"


def spoken_email(text: str) -> str:
    """As dictated -> an address, spaces and case gone, nothing checked yet.

    ``ana punto garcia arroba gmail punto com`` -> ``ana.garcia@gmail.com``. An
    address that already is one just loses its spaces and its case, which is
    what the scorer does to it.
    """
    folded = _fold(text)
    for filler in _EMAIL_FILLER:
        folded = _replace_word(folded, filler, " ")
    folded = _digit_words(folded)
    for spoken, symbol in EMAIL_SPOKEN:
        folded = _replace_word(folded, spoken, symbol)
    return _alias_domain(_WS.sub("", folded))


def check_email(text: str) -> EmailCheck:
    """Map the dictation, then let ``email-validator`` judge the syntax. No DNS."""
    address = spoken_email(text)
    try:
        result = validate_email(address, check_deliverability=False)
    except EmailNotValidError as exc:
        return EmailCheck(normalized=address, valid=False, detail=str(exc))
    return EmailCheck(normalized=result.normalized.casefold(), valid=True)


def spoken_phone(text: str) -> str:
    """As dictated -> the characters ``phonenumbers`` wants: digits and a leading ``+``."""
    folded = _fold(text)
    for word in _PHONE_PREFIX_WORDS:
        folded = _replace_word(folded, word, "+")
    folded = _digit_words(folded)
    digits = _NON_DIGIT.sub("", folded)
    return f"+{digits}" if folded.lstrip().startswith("+") else digits


def check_phone(text: str, region: str = "ES") -> PhoneCheck:
    """Map the dictation, parse it for ``region``, format E.164.

    A bare nine-digit Spanish number gets its ``+34``; ``0034`` and ``34`` prefixes
    are understood. A number of the wrong length is not possible and the caller
    should say it again.
    """
    raw = spoken_phone(text)
    try:
        number = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException as exc:
        return PhoneCheck(normalized=raw, possible=False, valid=False, detail=str(exc))
    possible = phonenumbers.is_possible_number(number)
    if not possible:
        return PhoneCheck(
            normalized=raw,
            possible=False,
            valid=False,
            detail=f"{len(_NON_DIGIT.sub('', raw))} digits is not a {region} number",
        )
    kind_code = phonenumbers.number_type(number)
    kind: Literal["mobile", "fixed_line", "other", "invalid"]
    if kind_code == phonenumbers.PhoneNumberType.MOBILE:
        kind = "mobile"
    elif kind_code == phonenumbers.PhoneNumberType.FIXED_LINE:
        kind = "fixed_line"
    elif kind_code == phonenumbers.PhoneNumberType.UNKNOWN:
        kind = "invalid"
    else:
        kind = "other"
    return PhoneCheck(
        normalized=phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164),
        possible=True,
        valid=phonenumbers.is_valid_number(number),
        kind=kind,
    )
