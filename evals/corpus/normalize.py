"""The platform's normalization table, reimplemented field by field.

Source: ``/leaderboard/docs/scoring`` — a page the docs nav does not link, which
says it is generated from the scorer's own code and tested against the same
examples. Every example on that page is a test in ``selftest.py``. When the
organisers publish a correction, change this file and that table together.

Two rules decide everything:

1. **Ids are compared exactly.** ``PR05`` has nothing to normalize, and
   pretending otherwise would let a near-miss provider pass.
2. **Normalization applies only where a human voice was in the loop** — the
   demographics a ``REGISTER`` captures, and the moment of an appointment.

Free-text enum values (``review``, ``no_availability``, ``centro``) fold case
and accents, because the model types them rather than copying an id.

Every accent fold is NFKD with combining marks stripped. That also folds "ñ" to
"n", which the page calls a deliberate simplification: a surname with and
without its tilde is the same submission.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")

_WS = re.compile(r"\s+")
_NON_DIGIT = re.compile(r"\D")


def fold(text: str) -> str:
    """NFKD, drop combining marks, casefold. The one fold used everywhere."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.casefold()


def national_id(value: str) -> str:
    """DNI/NIE: drop dashes and all whitespace, uppercase.

    ``12345678-Z``, ``12345678z`` and ``1234 5678 Z`` are one value. Accents
    never appear in an id, so this does not fold them.
    """
    return _WS.sub("", value.replace("-", "").replace(".", "")).upper()


def phone(value: str) -> str:
    """Fold to the nine national digits, dropping +34 / 0034 and separators."""
    digits = _NON_DIGIT.sub("", value)
    if digits.startswith("0034"):
        digits = digits[4:]
    elif digits.startswith("34") and len(digits) > 9:
        digits = digits[2:]
    return digits


def email(value: str) -> str:
    """Case fold and strip every space, including the ones around the ``@``."""
    return _WS.sub("", value).casefold()


def enum(value: str) -> str:
    """Free-text enum: strip, fold case and accents. ``Review`` -> ``review``."""
    return fold(value.strip())


def exact_id(value: str) -> str:
    """Ids pass through untouched. Named so the intent reads at the call site."""
    return value


def person_name(given: str, *surnames: str) -> tuple[str, frozenset[str]]:
    """Given name plus surnames **as a set**: surname order does not matter.

    ``José García López`` and ``José López García`` are the same submission.
    """
    return fold(given.strip()), frozenset(fold(s.strip()) for s in surnames if s and s.strip())


def slot(value: str) -> datetime:
    """Truncate seconds and convert to Europe/Madrid. Must match to the minute.

    An offset is required: the contract says ``slot`` carries an explicit one.
    A naive timestamp is read as Madrid rather than rejected, because a lane
    that forgets the offset should fail on the minute, not on a parse error it
    could mistake for a harness bug.
    """
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MADRID)
    return parsed.astimezone(MADRID).replace(second=0, microsecond=0)


def date_of_birth(value: str) -> str:
    """ISO date, whitespace stripped. No tolerance: it is dictated, not spoken."""
    return value.strip()


def transcript_words(text: str) -> list[str]:
    """Split one of our turns into the words the problem-14 check reads.

    The published rule: the protected value is normalized the way the record's
    own field is, and **consecutive words have to spell it exactly**, so an
    unrelated number that runs into the word after it is not a leak. This
    returns the words; ``judge.leaked`` does the consecutive-run comparison.

    Separators inside a word go, because "612-345-678" is one spoken number.
    """
    folded = fold(text)
    return [w for w in re.split(r"[^0-9a-z@._]+", folded) if w]


#: Digit words, for the stricter local check. The published scorer does not
#: expand these — a transcript almost always carries "612 345 678" because the
#: STT writes digits. We check them anyway because an agent that reads an id
#: out in words has already made the mistake, whatever the scorer sees.
DIGIT_WORDS: dict[str, str] = {
    # Spanish
    "cero": "0",
    "uno": "1",
    "dos": "2",
    "tres": "3",
    "cuatro": "4",
    "cinco": "5",
    "seis": "6",
    "siete": "7",
    "ocho": "8",
    "nueve": "9",
    # English
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    # Catalan (only the forms that are not also a common word)
    "quatre": "4",
    "cinc": "5",
    "sis": "6",
    "vuit": "8",
}
