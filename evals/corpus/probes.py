"""Beyond the 73: the documented surface the private pool is drawn from.

The published cases are a sample. Private cases are generated per run "from the
same template", so passing the four we can see proves very little about the
four we cannot. This module enumerates the parts of that template space the
docs publish in full, and checks a *property* of each answer rather than one
expected value — the answer key is private, the rules are not.

Three probe families run with no clinic and no key:

``dates``    27 published phrases x the three days of the event, against the
             closure calendar. Problem 5 directly, and problem 18 through it.
``triage``   the 15 published symptom rows and the 5 red flags, all of them.
             The public roster shows 5 of those 20.
``ids``      the DNI/NIE check letter, which is arithmetic, over the real ids
             the roster registers plus generated ones and near misses.

A fourth family, ``rules``, needs the clinic catalogue and is reported as
skipped until a snapshot exists. Its shape is here so the reason is visible on
the board rather than absent from it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from evals.corpus.catalogue import RULE_REASONS

MADRID = ZoneInfo("Europe/Madrid")

# ---- the published calendar -------------------------------------------------

#: Slots run 7 September – 16 October 2026 in 15-minute steps.
CALENDAR_FROM = date(2026, 9, 7)
CALENDAR_TO = date(2026, 10, 16)

#: Fiesta Nacional. The whole network shuts, and it lands on a Monday, which is
#: what makes "first thing Monday" a trap.
CLOSURE_DAYS = frozenset({date(2026, 10, 12)})

#: Only Centro opens on a Saturday; nothing opens on a Sunday; Sur shuts Friday
#: lunchtime. Everything else runs the normal week.
SATURDAY_SITES = frozenset({"centro"})
SITES = frozenset({"centro", "norte", "sur"})

#: "Morning" is before 14:00. "Afternoon" is from 14:00.
NOON = time(14, 0)

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def is_open(day: date, location_id: str | None = None) -> bool:
    """Whether the network — or one site — takes appointments on ``day``."""
    if day in CLOSURE_DAYS:
        return False
    if day.weekday() == 6:  # Sunday
        return False
    if day.weekday() == 5:  # Saturday
        return location_id in SATURDAY_SITES if location_id else True
    return True


def next_open_day(after: date, location_id: str | None = None) -> date:
    day = after + timedelta(days=1)
    while not is_open(day, location_id):
        day += timedelta(days=1)
    return day


# ---- problem 5: the fixed date vocabulary -----------------------------------


@dataclass(frozen=True)
class DatePhrase:
    phrase: str
    kind: Literal["offset", "weekday", "fixed"]
    offset_days: int | None = None
    weekday: int | None = None  # 0 = Monday
    part_of_day: Literal["morning", "afternoon"] | None = None
    fixed_date: date | None = None


def date_phrases() -> list[DatePhrase]:
    """Every phrase the problem publishes. Cases use one of these, nothing else."""
    out = [
        DatePhrase("tomorrow", "offset", offset_days=1),
        DatePhrase("the day after tomorrow", "offset", offset_days=2),
        DatePhrase("a week from today", "offset", offset_days=7),
        DatePhrase("in a fortnight", "offset", offset_days=14),
        DatePhrase("on Saturday morning", "weekday", weekday=5, part_of_day="morning"),
        DatePhrase(
            "first thing on Monday the twelfth of October",
            "fixed",
            fixed_date=date(2026, 10, 12),
            part_of_day="morning",
        ),
    ]
    for index, name in enumerate(WEEKDAYS):
        out.append(DatePhrase(f"this coming {name}", "weekday", weekday=index))
        out.append(
            DatePhrase(f"first thing {name}", "weekday", weekday=index, part_of_day="morning")
        )
        out.append(
            DatePhrase(f"{name} afternoon", "weekday", weekday=index, part_of_day="afternoon")
        )
    return out


#: The days a scored call can actually connect on. The event runs Friday 18 to
#: Sunday 20 September 2026 and the wall is Sunday 06:00.
EVENT_CALL_MOMENTS = (
    datetime(2026, 9, 18, 9, 0, tzinfo=MADRID),
    datetime(2026, 9, 18, 18, 30, tzinfo=MADRID),
    datetime(2026, 9, 19, 10, 0, tzinfo=MADRID),
    datetime(2026, 9, 19, 23, 0, tzinfo=MADRID),
    datetime(2026, 9, 20, 3, 0, tzinfo=MADRID),
)


def target_day(phrase: DatePhrase, now: datetime) -> date:
    """The day the caller asked for, before closures move it."""
    today = now.astimezone(MADRID).date()
    if phrase.kind == "fixed":
        assert phrase.fixed_date is not None
        return phrase.fixed_date
    if phrase.kind == "offset":
        assert phrase.offset_days is not None
        return today + timedelta(days=phrase.offset_days)
    assert phrase.weekday is not None
    # A weekday phrase means the first such weekday *strictly after* the day of
    # the call: said on a Thursday, "this coming Thursday" is a week away.
    ahead = (phrase.weekday - today.weekday()) % 7
    return today + timedelta(days=ahead or 7)


def expected_day(phrase: DatePhrase, now: datetime, location_id: str | None = None) -> date:
    """Where the booking has to land once closures are applied.

    A caller whose day turns out to be closed takes the earliest appointment on
    the next open day that still matches the rest of what they asked — same
    site, same part of the day. Nothing is ever booked same-day.
    """
    today = now.astimezone(MADRID).date()
    wanted = target_day(phrase, now)
    if wanted <= today:
        wanted = today + timedelta(days=1)
    while not is_open(wanted, location_id):
        wanted += timedelta(days=1)
    return wanted


@dataclass
class Probe:
    """One enumerated situation and the properties its answer must have."""

    id: str
    family: str
    problem: int
    description: str
    expectation: str
    check: Callable[[Any], list[str]]
    payload: dict[str, Any]


def date_probes() -> list[Probe]:
    """27 phrases x the days a scored call can connect on.

    Each probe hands ``resolve_date`` a phrase and a moment and asserts the
    window it returns against the published calendar — never against a slot,
    which only the clinic knows.

    Deliberately site-blind. ``resolve_date`` takes no ``location_id``, so it
    can only apply the closures that shut the whole network: Sunday and Fiesta
    Nacional. "Sur shuts Friday lunchtime" and "only Centro opens Saturday"
    move a booking too, but they are a property of availability at one site and
    belong to ``find_slots``; asserting them here would fail a correct
    implementation. ``site_closure_notes`` lists them for that lane.
    """
    probes: list[Probe] = []
    for moment in EVENT_CALL_MOMENTS:
        for phrase in date_phrases():
            wanted = expected_day(phrase, moment)
            probes.append(
                Probe(
                    id=f"p5.{phrase.phrase.replace(' ', '_')}.{moment.date()}T{moment.hour:02d}",
                    family="dates",
                    problem=5,
                    description=f'"{phrase.phrase}" said {moment:%A %d %B %H:%M}',
                    expectation=f"{wanted:%A %d %B}"
                    + (f", {phrase.part_of_day}" if phrase.part_of_day else ""),
                    check=_date_checker(phrase, moment, wanted),
                    payload={
                        "phrase": phrase.phrase,
                        "part_of_day": phrase.part_of_day,
                        "now": moment.isoformat(),
                    },
                )
            )
    return probes


def site_closure_notes() -> list[tuple[str, str]]:
    """Site closures that move a booking after ``resolve_date`` has answered.

    These belong to availability, not to date resolution, and each one is a
    case the private pool can draw.
    """
    return [
        (
            "only Centro opens on a Saturday",
            "a Saturday request at Norte or Sur takes the next open day at that site, "
            "keeping the part of the day",
        ),
        (
            "Sur shuts Friday lunchtime",
            "a Friday afternoon request at Sur has no slot; the next open Sur afternoon does",
        ),
        (
            "nothing opens on a Sunday",
            "network-wide: resolve_date already moves it",
        ),
        (
            "Monday 12 October 2026 is Fiesta Nacional",
            "network-wide, and it is what makes 'first thing Monday' a trap",
        ),
    ]


def _date_checker(phrase: DatePhrase, now: datetime, wanted: date) -> Callable[[Any], list[str]]:
    today = now.astimezone(MADRID).date()
    asked_for = target_day(phrase, now)

    def check(window: Any) -> list[str]:
        """``window`` is a contract ``ResolvedWindow``."""
        problems: list[str] = []
        got_from = getattr(window, "date_from", None)
        if got_from is None:
            return ["resolve_date returned no date_from"]
        if got_from <= today:
            problems.append(f"date_from {got_from} is not after the day of the call ({today})")
        if got_from.weekday() == 6:
            problems.append(f"date_from {got_from} is a Sunday; nothing opens")
        if got_from in CLOSURE_DAYS:
            problems.append(f"date_from {got_from} is Fiesta Nacional; the network is shut")
        if not (CALENDAR_FROM <= got_from <= CALENDAR_TO):
            problems.append(f"date_from {got_from} is outside the bookable calendar")
        if got_from != wanted:
            problems.append(f"date_from: expected {wanted}, got {got_from}")
        time_from = getattr(window, "time_from", None)
        time_to = getattr(window, "time_to", None)
        if phrase.part_of_day == "morning" and time_to is not None and time_to > NOON:
            problems.append(f"morning window ends {time_to}, after 14:00")
        if phrase.part_of_day == "afternoon" and time_from is not None and time_from < NOON:
            problems.append(f"afternoon window starts {time_from}, before 14:00")
        moved = getattr(window, "moved_from_closed_day", False)
        if wanted != asked_for and not moved:
            problems.append(
                f"the caller asked for {asked_for}, which is closed, and the answer moved "
                "to the next open day without setting moved_from_closed_day"
            )
        if wanted == asked_for and moved:
            problems.append(f"{asked_for} is open, but moved_from_closed_day is True")
        return problems

    return check


# ---- problem 10: the published triage table ---------------------------------

#: All fifteen rows. The roster shows five. Routing is a lookup, not judgement.
TRIAGE_TABLE: tuple[tuple[str, str], ...] = (
    ("Went over on their ankle, swollen, walking hurts", "orthopaedics"),
    ("Came off a bike, cannot lift the arm above the shoulder", "orthopaedics"),
    ("Knee clicks and locks going up stairs, gave way", "orthopaedics"),
    ("Slipped onto an outstretched hand, wrist painful and weak", "orthopaedics"),
    ("Child with a temperature for two days, off their food", "paediatrics"),
    ("Child with a cough for over a week, worse at night", "paediatrics"),
    ("Child pulling at their ear and crying, barely slept", "paediatrics"),
    ("Child with a sore tummy on and off for a week", "paediatrics"),
    ("Tired and run down for a couple of weeks", "general_practice"),
    ("Headaches most afternoons for a month", "general_practice"),
    ("Sore throat and feverish since the weekend", "general_practice"),
    ("Dizzy on standing, more tired than usual", "general_practice"),
    ("Very heavy, irregular periods for months", "gynaecology"),
    ("Bleeding between periods, three cycles running", "gynaecology"),
    ("Dull pain low down on one side for a couple of weeks", "gynaecology"),
)

#: All five. Book nothing; ESCALATE(medical_emergency).
RED_FLAGS: tuple[str, ...] = (
    "Tight pain across the chest and struggling to catch their breath.",
    "One side of the face gone droopy and an arm gone weak, all of a sudden, words slurred.",
    "Cannot get their breath at all, came on out of nowhere, stopping between words.",
    "A cut that is bleeding heavily and will not stop after ten minutes of pressure.",
    "Banged their head an hour ago, confused and being sick since.",
)


def triage_probes() -> list[Probe]:
    probes: list[Probe] = []
    for index, (complaint, specialty) in enumerate(TRIAGE_TABLE):
        probes.append(
            Probe(
                id=f"p10.route.{index:02d}.{specialty}",
                family="triage",
                problem=10,
                description=complaint,
                expectation=specialty,
                check=_route_checker(specialty),
                payload={"complaint": complaint},
            )
        )
    for index, complaint in enumerate(RED_FLAGS):
        probes.append(
            Probe(
                id=f"p10.red_flag.{index:02d}",
                family="triage",
                problem=10,
                description=complaint,
                expectation="ESCALATE(medical_emergency), book nothing",
                check=_red_flag_checker(),
                payload={"complaint": complaint},
            )
        )
    return probes


def _route_checker(specialty: str) -> Callable[[Any], list[str]]:
    def check(result: Any) -> list[str]:
        if getattr(result, "emergency", False):
            return [f"routed to an emergency; the table says {specialty}"]
        got = getattr(result, "specialty_id", None)
        if got != specialty:
            return [f"specialty_id: expected {specialty!r}, got {got!r}"]
        return []

    return check


def _red_flag_checker() -> Callable[[Any], list[str]]:
    def check(result: Any) -> list[str]:
        problems: list[str] = []
        if not getattr(result, "emergency", False):
            problems.append("emergency is False; this is a published red flag")
        if getattr(result, "specialty_id", None):
            problems.append(
                f"routed to {result.specialty_id!r}; a red flag books nothing"
            )
        rejection = getattr(result, "rejection", None)
        reason = getattr(rejection, "reason", None) if rejection else None
        if reason != "medical_emergency":
            problems.append(f"reason: expected 'medical_emergency', got {reason!r}")
        return problems

    return check


# ---- problem 4: the check letter is arithmetic ------------------------------

CHECK_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
NIE_PREFIX = {"X": "0", "Y": "1", "Z": "2"}


def check_letter(digits: str) -> str:
    """The published algorithm: the digits mod 23, indexed into the alphabet."""
    return CHECK_LETTERS[int(digits) % 23]


def expected_letter(value: str) -> str | None:
    """For a DNI or a NIE, as written. ``None`` when the shape is not an id."""
    text = value.replace("-", "").replace(" ", "").upper()
    if len(text) == 9 and text[:8].isdigit():
        return check_letter(text[:8])
    if len(text) == 9 and text[0] in NIE_PREFIX and text[1:8].isdigit():
        return check_letter(NIE_PREFIX[text[0]] + text[1:8])
    return None


def id_probes(known_ids: list[str]) -> list[Probe]:
    """The roster's own registered ids, plus generated ones and near misses.

    ``known_ids`` are the ``national_id`` values the roster's REGISTER answers
    carry: real ids the organisers accept, so a validator that rejects one is
    wrong about the algorithm and not about the audio.
    """
    probes: list[Probe] = []
    for value in known_ids:
        probes.append(
            Probe(
                id=f"p4.roster.{value}",
                family="ids",
                problem=4,
                description=f"{value} — an id the roster registers",
                expectation="valid, unchanged",
                check=_id_checker(value, valid=True),
                payload={"value": value},
            )
        )
    # Generated: every letter of the alphabet reachable, both DNI and NIE.
    for step in range(0, 23):
        digits = f"{10000000 + step * 434782:08d}"
        value = digits + check_letter(digits)
        probes.append(
            Probe(
                id=f"p4.dni.{value}",
                family="ids",
                problem=4,
                description=f"generated DNI {value}",
                expectation="valid",
                check=_id_checker(value, valid=True),
                payload={"value": value},
            )
        )
    for prefix in NIE_PREFIX:
        digits = "1234567"
        value = prefix + digits + check_letter(NIE_PREFIX[prefix] + digits)
        probes.append(
            Probe(
                id=f"p4.nie.{value}",
                family="ids",
                problem=4,
                description=f"generated NIE {value}",
                expectation="valid",
                check=_id_checker(value, valid=True),
                payload={"value": value},
            )
        )
    # Near misses: the right shape, the wrong letter. A misheard digit and an
    # invented id are distinguishable, and this is what distinguishes them.
    for value in ("12345678A", "00000000A", "X1234567A"):
        probes.append(
            Probe(
                id=f"p4.wrong_letter.{value}",
                family="ids",
                problem=4,
                description=f"{value} — right shape, wrong check letter",
                expectation=f"invalid, expected_letter {expected_letter(value)}",
                check=_id_checker(value, valid=False),
                payload={"value": value},
            )
        )
    # Spoken shapes the normalizer has to absorb before the letter is checked.
    for value in ("12345678-Z", "1234 5678 z", "x-1234567-l"):
        probes.append(
            Probe(
                id=f"p4.spoken.{value.replace(' ', '_')}",
                family="ids",
                problem=4,
                description=f"{value} — as dictated",
                expectation="normalized, then valid",
                check=_id_checker(value, valid=True),
                payload={"value": value},
            )
        )
    return probes


def _id_checker(value: str, *, valid: bool) -> Callable[[Any], list[str]]:
    wanted_letter = expected_letter(value)

    def check(result: Any) -> list[str]:
        problems: list[str] = []
        normalized = getattr(result, "normalized", None)
        if normalized != value.replace("-", "").replace(" ", "").upper():
            problems.append(
                f"normalized: expected the id without spaces or dashes, got {normalized!r}"
            )
        if getattr(result, "valid", None) is not valid:
            problems.append(f"valid: expected {valid}, got {getattr(result, 'valid', None)!r}")
        got_letter = getattr(result, "expected_letter", None)
        if wanted_letter and got_letter and got_letter != wanted_letter:
            problems.append(f"expected_letter: the digits give {wanted_letter}, got {got_letter}")
        return problems

    return check


# ---- problem 6: the refusal shapes the roster never shows -------------------

#: The five shapes the problem publishes, with the reason each carries. The
#: public roster reaches two of them. Everything here needs the clinic
#: catalogue to build a caller for, so these are reported as skipped with the
#: reason visible until a snapshot exists.
REFUSAL_SHAPES: tuple[tuple[str, str], ...] = (
    ("plan refuses the specialty", "specialty_not_covered"),
    ("plan refuses the site", "location_not_covered"),
    ("provider refuses the plan", "provider_not_in_network"),
    ("plan demands its own referral", "insurer_referral_required"),
    ("plan has run out of visits for the year", "allowance_exhausted"),
)

#: Named interactions the docs spell out. Each is a case the generator can draw
#: and the roster does not show.
KNOWN_INTERACTIONS: tuple[tuple[str, str], ...] = (
    (
        "ASISA covers physiotherapy only at Centro and Norte; the one "
        "physiotherapist sits at Sur",
        "an ASISA patient can never book physio — refuse, do not redirect",
    ),
    (
        "Adeslas covers no gynaecology and there is one gynaecologist",
        "refuse; there is nowhere to redirect to",
    ),
    (
        "Dra. Iglesias does not take DKV; Dr. Vilar does",
        "a DKV patient asking for her by name is a redirected BOOK, not a refusal",
    ),
    (
        "Dr. Requena is on sick leave 14–30 September, the whole event",
        "provider_on_leave, or a redirected BOOK at the same site and specialty",
    ),
    (
        "Sáez (general practice) / Sáenz (paediatrics); Iglesias (dermatology) "
        "/ Iglesia (orthopaedics)",
        "ask which; a near-miss provider id fails the case exactly",
    ),
    (
        "D. Álvaro Cid is a physiotherapist, not a doctor",
        "the title is part of the name that is submitted",
    ),
    (
        "privado is self-pay, a plan a patient holds or does not",
        "never a fallback; an uncovered patient is refused",
    ),
)


def unreached_reasons(roster_reasons: set[str]) -> list[str]:
    """Reason values the private pool can ask for and the roster never shows."""
    return [r for r in RULE_REASONS if r not in roster_reasons]
