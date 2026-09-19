"""diary/ tools - the agenda.

Owner: the diary lane. Keep the signatures exactly as ``vortex/contract.py``
declares them.

What the docs say this lane must get right (clinic docs, "Calendar"):

- Dates resolve against ``ctx.now`` (the moment the call connected, in
  Europe/Madrid). Never against the machine clock.
- Nothing is booked on the day of the call. "Earliest" starts tomorrow.
- Slots run 7 Sep - 16 Oct 2026 in 15-minute steps. /availability rejects a
  span longer than 14 days (422) and any date outside the window.
- Monday 12 October is closed. Only Centro opens on Saturday. Nothing opens
  on Sunday. Sur shuts Friday lunchtime.
- "Morning" is before 14:00; "afternoon" from 14:00.
- A weekday phrase is the first such weekday strictly after the call's day.
- The appointment type comes from /availability's ``appointment_type``, never
  from the caller. Submit the id on the slot.
- ``appointment_id`` comes only from /patients/{id}/appointments.

Two distinctions this lane exists to keep apart:

- **Full vs shut.** Empty ``slots`` with empty ``blocked`` is a full calendar
  (``no_availability``). Empty ``slots`` because every site in scope is closed
  for the whole window is ``clinic_closed`` - which is a *retry on the next
  open day*, never a final answer to the caller (problem 5). ``blocked`` is
  neither: it names the rule that stopped a professional, and the rules lane
  decides whether that is a redirect or a refusal.
- **Network-wide vs per site.** ``resolve_date`` takes no ``location_id``, so
  it can only move a day the whole network shuts (Sunday, Fiesta Nacional).
  "Only Centro opens Saturday" and "Sur shuts Friday lunchtime" are properties
  of availability at one site: they surface as an empty ``find_slots`` answer
  for that day, and the caller is then offered the next open day that keeps
  the rest of the request.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, time, timedelta

from vortex.clinic.client import ClinicApiError
from vortex.contract import (
    MADRID,
    Appointment,
    AppointmentList,
    AvailabilityResponse,
    AvailabilityResult,
    BlockedProvider,
    BookAction,
    BookingResult,
    CancelAction,
    CancelResult,
    Catalogue,
    FindSlotsInput,
    ListAppointmentsInput,
    PartOfDay,
    PrepareBookingInput,
    PrepareCancelInput,
    PrepareRescheduleInput,
    Rejection,
    RescheduleAction,
    RescheduleResult,
    ResolveDateInput,
    ResolvedWindow,
    Slot,
    ToolContext,
)

#: "Morning" is before 14:00. "Afternoon" is from 14:00. Published, not a guess.
MORNING_ENDS = time(14, 0)
DAY_ENDS = time(23, 59)

#: ``date_to - date_from``. The API rejects a span longer than 14 days, so every
#: window is walked in chunks of at most 14 calendar days.
_MAX_SPAN_DAYS = 13

#: How far a closed day may push a request before we call it unbookable.
_MAX_MOVE_DAYS = 21

#: How many directory records ``_locate_appointment`` may walk as a last resort.
_MAX_DIRECTORY_SCAN = 25

#: A status that means the visit is over or already gone. Anything else is live.
_DEAD_STATUSES = frozenset({"cancelled", "canceled", "completed", "no_show", "noshow", "attended"})

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_MONTHS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)  # fmt: skip

# The agent answers in English, but 4 of the 73 published cases are not English.
# Non-English words are folded onto their English equivalent before parsing, so
# there is one grammar to maintain instead of three.
_WORD_ALIASES: dict[str, str] = {
    # weekdays: Spanish, then Catalan
    "lunes": "monday",
    "martes": "tuesday",
    "miercoles": "wednesday",
    "jueves": "thursday",
    "viernes": "friday",
    "sabado": "saturday",
    "domingo": "sunday",
    "dilluns": "monday",
    "dimarts": "tuesday",
    "dimecres": "wednesday",
    "dijous": "thursday",
    "divendres": "friday",
    "dissabte": "saturday",
    "diumenge": "sunday",
    # months: Spanish, then Catalan where it differs
    "enero": "january",
    "febrero": "february",
    "marzo": "march",
    "abril": "april",
    "mayo": "may",
    "junio": "june",
    "julio": "july",
    "agosto": "august",
    "septiembre": "september",
    "setiembre": "september",
    "octubre": "october",
    "noviembre": "november",
    "diciembre": "december",
    "gener": "january",
    "febrer": "february",
    "marc": "march",
    "maig": "may",
    "juny": "june",
    "juliol": "july",
    "agost": "august",
    "setembre": "september",
    "novembre": "november",
    "desembre": "december",
    # the one preposition the date grammar needs
    "de": "of",
    "d": "of",
}

#: Articles and particles that carry nothing here. None of them is English.
_FILLER = frozenset({"el", "la", "els", "les", "lo", "los", "las", "un", "una", "i"})

#: Multi-word idioms, folded onto the English vocabulary. Order matters:
#: "pasado manana" must win before the bare "manana".
_IDIOMS: tuple[tuple[str, str], ...] = (
    (r"\bpor la manana\b", "morning"),
    (r"\bpor la tarde\b", "afternoon"),
    (r"\bal mati\b", "morning"),
    (r"\ba la tarda\b", "afternoon"),
    (r"\ba primera hora (?:de la|del|de|d)?\s*", "first thing on "),
    (r"\bpasado manana\b", "the day after tomorrow"),
    (r"\bdema passat\b", "the day after tomorrow"),
    (r"\bmanana\b", "tomorrow"),
    (r"\bdema\b", "tomorrow"),
    (r"\bdentro de (?:una|1) semana\b", "a week from today"),
    (r"\bdins d? ?(?:una|1) setmana\b", "a week from today"),
    (r"\bdentro de (?:dos|2) semanas\b", "in a fortnight"),
    (r"\bdentro de (?:quince|15) dias\b", "in a fortnight"),
    (r"\bd? ?aqui a (?:quinze|15) dies\b", "in a fortnight"),
    (r"\b(?:este|aquest) (\w+) que ve?ne?\b", r"this coming \1"),
    (r"\b(?:el )?proxim[oa] (\w+)\b", r"this coming \1"),
    (r"\bque viene\b", ""),
)

#: Offsets from the day of the call. The four published offset phrases, plus the
#: shapes a caller reaches for on the way to them.
_DAY_OFFSETS: dict[str, int] = {
    "today": 0,
    "tomorrow": 1,
    "the day after tomorrow": 2,
    "day after tomorrow": 2,
    "in two days": 2,
    "a week from today": 7,
    "in a week": 7,
    "in one week": 7,
    "in seven days": 7,
    "in a fortnight": 14,
    "a fortnight from today": 14,
    "in two weeks": 14,
    "in fifteen days": 14,
}

#: "the earliest" names no day: it asks us to search. Answered with a window.
_EARLIEST_PHRASES = frozenset(
    {
        "",
        "earliest",
        "the earliest",
        "the earliest available appointment",
        "the earliest appointment",
        "as soon as possible",
        "asap",
        "anytime",
        "whenever",
        "lo antes posible",
        "cuanto antes",
        "com abans millor",
    }
)

#: Day of the month, as a word. English ordinals and Spanish/Catalan cardinals
#: share the slot: "the twelfth of October" and "doce de octubre" are one date.
_DAY_NUMBERS: dict[str, int] = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12,
    "thirteenth": 13, "fourteenth": 14, "fifteenth": 15, "sixteenth": 16,
    "seventeenth": 17, "eighteenth": 18, "nineteenth": 19, "twentieth": 20,
    "twenty first": 21, "twenty second": 22, "twenty third": 23, "twenty fourth": 24,
    "twenty fifth": 25, "twenty sixth": 26, "twenty seventh": 27, "twenty eighth": 28,
    "twenty ninth": 29, "thirtieth": 30, "thirty first": 31,
    "primero": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13,
    "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18,
    "diecinueve": 19, "veinte": 20, "veintiuno": 21, "veintidos": 22, "veintitres": 23,
    "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26, "veintisiete": 27,
    "veintiocho": 28, "veintinueve": 29, "treinta": 30, "treinta of uno": 31,
}  # fmt: skip


# ---------------------------------------------------------------------------
# The calendar: which days the network, or one site, actually opens
# ---------------------------------------------------------------------------


def _open_sites(catalogue: Catalogue, day: date) -> set[str]:
    """Every site that takes appointments on ``day``, from its published hours."""
    if day in catalogue.closure_days:
        return set()
    return {
        loc.location_id
        for loc in catalogue.locations
        if any(h.weekday == day.weekday() for h in loc.hours)
    }


def _is_open(catalogue: Catalogue, day: date, sites: set[str] | None = None) -> bool:
    """Whether ``day`` opens at all, or at one of ``sites`` when given."""
    open_today = _open_sites(catalogue, day)
    return bool(open_today & sites) if sites is not None else bool(open_today)


def _first_open_day(catalogue: Catalogue, day: date, sites: set[str] | None = None) -> date | None:
    """``day`` itself when it opens, otherwise the next day that does."""
    for offset in range(_MAX_MOVE_DAYS + 1):
        candidate = day + timedelta(days=offset)
        if catalogue.bookable_to and candidate > catalogue.bookable_to:
            return None
        if _is_open(catalogue, candidate, sites):
            return candidate
    return None


def _next_weekday(today: date, weekday: int) -> date:
    """The first ``weekday`` (0=Monday) strictly after ``today``.

    Said on a Thursday, "this coming Thursday" is seven days away. This is the
    rule problem 5 fails most often.
    """
    ahead = (weekday - today.weekday()) % 7
    return today + timedelta(days=ahead or 7)


def _spans(date_from: date, date_to: date) -> list[tuple[date, date]]:
    """``[date_from, date_to]`` cut into chunks /availability accepts (max 14 days)."""
    out: list[tuple[date, date]] = []
    cursor = date_from
    while cursor <= date_to:
        end = min(cursor + timedelta(days=_MAX_SPAN_DAYS), date_to)
        out.append((cursor, end))
        cursor = end + timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# resolve_date: the closed vocabulary of problem 5
# ---------------------------------------------------------------------------


def _canonical(phrase: str) -> str:
    """Fold a spoken phrase onto the English vocabulary the grammar below parses."""
    text = unicodedata.normalize("NFKD", phrase)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("-", " ").replace("'", " ")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for pattern, replacement in _IDIOMS:
        text = re.sub(pattern, replacement, text)
    tokens = [t for t in text.split() if t not in _FILLER]
    return " ".join(_WORD_ALIASES.get(t, t) for t in tokens).strip()


def _split_part_of_day(text: str) -> tuple[str, PartOfDay | None]:
    """Pull "first thing" / "morning" / "afternoon" off the phrase."""
    part: PartOfDay | None = None
    if text.startswith("first thing"):
        part = "morning"
        text = text[len("first thing") :].strip()
    for marker, value in (
        ("morning", "morning"),
        ("afternoon", "afternoon"),
        ("tarde", "afternoon"),
    ):
        if text == marker or text.endswith(" " + marker):
            part = part or value  # type: ignore[assignment]
            text = text[: len(text) - len(marker)].strip()
    # "on Saturday" -> "saturday", but never eat the "in" of "in a fortnight".
    if text not in _DAY_OFFSETS:
        for prefix in ("in the", "on the", "on", "in", "at", "of"):
            if text == prefix or text.startswith(prefix + " "):
                text = text[len(prefix) :].strip()
                break
    return text.strip(), part


def _day_number(word: str) -> int | None:
    """A day of the month, written as digits ("12", "12th") or as a word."""
    text = word.strip()
    digits = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?", text)
    if digits:
        value = int(digits.group(1))
        return value if 1 <= value <= 31 else None
    return _DAY_NUMBERS.get(text)


def _calendar_date(day_of_month: int, month: int, today: date) -> date | None:
    """The next occurrence of ``day_of_month`` in ``month``, from ``today`` on."""
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day_of_month)
        except ValueError:
            return None
        if candidate > today:
            return candidate
    return None


def _parse_day(text: str, today: date) -> date | None:
    """The day the caller asked for, before any closure moves it."""
    if text in _DAY_OFFSETS:
        return today + timedelta(days=_DAY_OFFSETS[text])

    iso = re.fullmatch(r"(\d{4}) (\d{1,2}) (\d{1,2})", text.replace("-", " "))
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None

    # "monday the twelfth of october", "12 of october", "october the 12th".
    weekday_names = "|".join(_WEEKDAYS)
    month_names = "|".join(_MONTHS)
    patterns = (
        rf"^(?:(?:{weekday_names}) )?(?:the )?([a-z0-9 ]+?) of ({month_names})(?: \d{{4}})?$",
        rf"^(?:(?:{weekday_names}) )?(?:the )?([a-z0-9 ]+?) ({month_names})(?: \d{{4}})?$",
        rf"^(?:(?:{weekday_names}) )?({month_names}) (?:the )?([a-z0-9 ]+?)$",
    )
    for index, pattern in enumerate(patterns):
        match = re.fullmatch(pattern, text)
        if not match:
            continue
        raw_day, raw_month = (
            (match.group(2), match.group(1)) if index == 2 else (match.group(1), match.group(2))
        )
        day_of_month = _day_number(raw_day)
        if day_of_month is None:
            continue
        return _calendar_date(day_of_month, _MONTHS.index(raw_month) + 1, today)

    # A weekday on its own, however the caller dressed it up.
    bare = re.sub(r"^(this|next)(?: coming)? ", "", text)
    bare = re.sub(r"^coming ", "", bare).strip()
    if bare in _WEEKDAYS:
        return _next_weekday(today, _WEEKDAYS.index(bare))
    return None


async def resolve_date(ctx: ToolContext, args: ResolveDateInput) -> ResolvedWindow:
    """Turn a colloquial phrase into a date window in Europe/Madrid.

    Everything is measured from ``ctx.now``, the moment the call connected.

    The window is one day wide: the day the caller named, moved forward when
    that day is shut network-wide (Sunday, Fiesta Nacional) or is not after the
    day of the call - nothing is booked same-day. ``moved_from_closed_day``
    says the answer is no longer the day that was asked for, so the
    conversation confirms it instead of assuming it.

    The exception is "the earliest", which names no day. That answers with a
    search window from the next open day, as wide as /availability accepts.

    Site closures ("only Centro opens Saturday", "Sur shuts Friday lunchtime")
    are *not* applied here: this tool takes no ``location_id``. They surface as
    an empty ``find_slots`` answer for that site and day.
    """
    catalogue = await ctx.clinic.catalogue()
    today = ctx.now.astimezone(MADRID).date()
    tomorrow = today + timedelta(days=1)

    text, part_from_phrase = _split_part_of_day(_canonical(args.phrase))
    part_of_day = args.part_of_day or part_from_phrase

    if text in _EARLIEST_PHRASES:
        opens = _first_open_day(catalogue, tomorrow)
        if opens is None:
            return _no_window(
                today,
                "no_availability",
                f"nothing opens within {_MAX_MOVE_DAYS} days of {tomorrow}",
            )
        date_to = opens + timedelta(days=_MAX_SPAN_DAYS)
        if catalogue.bookable_to:
            date_to = min(date_to, catalogue.bookable_to)
        return _window(opens, max(date_to, opens), part_of_day, moved=False)

    asked_for = _parse_day(text, today)
    if asked_for is None:
        return _no_window(
            today, "out_of_scope", f"date phrase outside the vocabulary: {args.phrase!r}"
        )
    if catalogue.bookable_from and asked_for < catalogue.bookable_from:
        asked_for = catalogue.bookable_from
    if catalogue.bookable_to and asked_for > catalogue.bookable_to:
        return _no_window(
            today,
            "no_availability",
            f"{asked_for} is past the last bookable day ({catalogue.bookable_to})",
        )

    # Never same-day, then walk forward over days the whole network shuts.
    wanted = max(asked_for, tomorrow)
    opens = _first_open_day(catalogue, wanted)
    if opens is None:
        return _no_window(
            today, "clinic_closed", f"nothing opens within {_MAX_MOVE_DAYS} days of {wanted}"
        )
    return _window(opens, opens, part_of_day, moved=opens != asked_for)


def _window(
    date_from: date, date_to: date, part_of_day: PartOfDay | None, *, moved: bool
) -> ResolvedWindow:
    time_from = time_to = None
    if part_of_day == "morning":
        time_from, time_to = time(0, 0), MORNING_ENDS
    elif part_of_day == "afternoon":
        time_from, time_to = MORNING_ENDS, DAY_ENDS
    return ResolvedWindow(
        date_from=date_from,
        date_to=date_to,
        time_from=time_from,
        time_to=time_to,
        moved_from_closed_day=moved,
    )


def _no_window(today: date, reason: str, detail: str) -> ResolvedWindow:
    return ResolvedWindow(
        date_from=today,
        date_to=today,
        rejection=Rejection(reason=reason, detail=detail),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# find_slots: real availability, filtered by what the caller asked for
# ---------------------------------------------------------------------------


def _scope_sites(catalogue: Catalogue, args: FindSlotsInput) -> set[str]:
    """The sites the request can land in: the named one, or every site that could serve it."""
    if args.location_id:
        return {args.location_id}
    providers = [
        p
        for p in catalogue.providers
        if (not args.provider_id or p.provider_id == args.provider_id)
        and (not args.specialty_id or p.specialty_id == args.specialty_id)
    ]
    sites = {loc for p in providers for loc in p.location_ids}
    return sites or {loc.location_id for loc in catalogue.locations}


def _keeps_blocked(
    catalogue: Catalogue, entry: BlockedProvider, sites: set[str], days: list[date]
) -> bool:
    """Whether a blocked provider is the real reason the caller got nothing.

    /availability reports its restriction metadata whether or not slots were
    asked for. A provider whose own sites are shut for the whole window was
    never going to be offered anyway, so naming their leave would name the
    wrong rule: the window is closed, not the diary blocked.
    """
    provider = next((p for p in catalogue.providers if p.provider_id == entry.provider_id), None)
    if provider is None:
        return True  # unknown to the catalogue: trust the clinic, keep the rule
    reachable = set(provider.location_ids) & sites
    return any(_is_open(catalogue, day, reachable) for day in days)


async def find_slots(ctx: ToolContext, args: FindSlotsInput) -> AvailabilityResult:
    """Real availability from the clinic, filtered by the caller's constraints.

    The window is walked in chunks /availability accepts (a span longer than 14
    days is a 422) and clamped to the bookable calendar. Slots on the day of
    the call are dropped: they exist in the answer and are never bookable.

    ``time_to`` is exclusive, so a morning window ending at 14:00 does not
    return the 14:00 slot - 14:00 is the afternoon.

    The platform names a ``blocked`` rule only when it stops the whole window
    asked for: one day past the end of a leave and the rule is gone from the
    answer, replaced by the slots after it (docs/evals-corpus.md). So when the
    walk comes back with slots and no rule, the slot-free head of the window -
    the stretch before the first slot, where the rule is still visible - is
    re-asked in API-sized chunks and whatever it names is carried. A wide
    search then reports both the October slots and the September leave.

    When nothing comes back the answer says which kind of nothing it is:
    ``clinic_closed`` when every site in scope is shut for the whole window
    (the caller takes the next open day), ``no_availability`` when the sites
    were open and the diaries were simply full. A non-empty ``blocked`` carries
    no rejection: naming the rule as a refusal is the rules lane's call.

    Problem 7: a true ``no_availability`` (never ``clinic_closed``, never a
    kept ``blocked`` rule) with ``args.widen_days`` set searches forward that
    many days past ``date_to`` once, under the same constraints, before giving
    up — so the caller can be offered the nearest thing that works.
    """
    catalogue = await ctx.clinic.catalogue()
    today = ctx.now.astimezone(MADRID).date()

    date_from = max(args.date_from, today + timedelta(days=1))
    date_to = args.date_to
    if catalogue.bookable_from:
        date_from = max(date_from, catalogue.bookable_from)
    if catalogue.bookable_to:
        date_to = min(date_to, catalogue.bookable_to)
    if date_from > date_to:
        return AvailabilityResult(
            rejection=Rejection(
                reason="no_availability",
                detail=(
                    f"nothing bookable between {args.date_from} and {args.date_to}: "
                    f"the window is in the past or outside the calendar"
                ),
            )
        )

    async def ask(span_from: date, span_to: date) -> AvailabilityResponse:
        """One ``/availability`` call with the caller's constraints, as given."""
        return await ctx.clinic.availability(
            date_from=span_from,
            date_to=span_to,
            provider_id=args.provider_id,
            specialty_id=args.specialty_id,
            location_id=args.location_id,
            patient_id=args.patient_id,
            insurer=[args.insurer] if args.insurer else None,
        )

    slots: list[Slot] = []
    blocked: dict[str, BlockedProvider] = {}
    appointment_type = None
    for span_from, span_to in _spans(date_from, date_to):
        try:
            answer = await ask(span_from, span_to)
        except ClinicApiError as exc:
            return AvailabilityResult(
                rejection=Rejection(
                    reason="no_availability",
                    detail=f"availability {span_from}..{span_to} failed: {exc}",
                )
            )
        slots.extend(answer.slots)
        for entry in answer.blocked:
            blocked.setdefault(entry.provider_id, entry)
        appointment_type = appointment_type or answer.appointment_type

    # A wide window that found slots hides the rule that emptied its head: the
    # platform only names a rule when it stops the whole window. Re-ask the
    # stretch before the first slot, where the rule is still reported.
    if slots and not blocked:
        head_to = min(s.start.astimezone(MADRID).date() for s in slots) - timedelta(days=1)
        for probe_from, probe_to in _spans(date_from, head_to):
            try:
                answer = await ask(probe_from, probe_to)
            except ClinicApiError:
                break  # best effort: the wide answer stands as it is
            slots.extend(answer.slots)
            for entry in answer.blocked:
                blocked.setdefault(entry.provider_id, entry)
            appointment_type = appointment_type or answer.appointment_type

    slots = [s for s in slots if s.start.astimezone(MADRID).date() > today]
    if args.time_from is not None or args.time_to is not None:
        low = args.time_from or time(0, 0)
        high = args.time_to
        slots = [
            s
            for s in slots
            if low <= s.start.astimezone(MADRID).time()
            and (high is None or s.start.astimezone(MADRID).time() < high)
        ]
    if args.language:
        speaks = {p.provider_id for p in catalogue.providers if args.language in p.languages}
        slots = [s for s in slots if s.provider_id in speaks]
    slots.sort(key=lambda s: (s.start, s.provider_id, s.location_id))

    sites = _scope_sites(catalogue, args)
    days = [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]
    window_opens = any(_is_open(catalogue, day, sites) for day in days)
    kept = [e for e in blocked.values() if _keeps_blocked(catalogue, e, sites, days)]

    rejection = None
    if not slots and not kept:
        rejection = Rejection(
            reason="clinic_closed" if not window_opens else "no_availability",
            detail=(
                f"every site in {sorted(sites)} is closed {date_from}..{date_to}"
                if not window_opens
                else f"no free slot {date_from}..{date_to} within the caller's constraints"
            ),
        )

    widened = False
    if rejection is not None and rejection.reason == "no_availability" and args.widen_days:
        further_to = date_to + timedelta(days=args.widen_days)
        if catalogue.bookable_to:
            further_to = min(further_to, catalogue.bookable_to)
        if further_to > date_to:
            extended = await find_slots(
                ctx,
                args.model_copy(
                    update={
                        "date_from": date_to + timedelta(days=1),
                        "date_to": further_to,
                        "widen_days": None,  # one widen per call: stop the recursion here
                    }
                ),
            )
            widened = True
            if extended.slots:
                return AvailabilityResult(
                    slots=extended.slots,
                    blocked=extended.blocked or kept,
                    appointment_type=appointment_type or extended.appointment_type,
                    rejection=None,
                    widened=True,
                )
            if extended.blocked:
                return AvailabilityResult(
                    blocked=extended.blocked,
                    appointment_type=appointment_type or extended.appointment_type,
                    rejection=None,
                    widened=True,
                )
            rejection = Rejection(
                reason="no_availability",
                detail=rejection.detail + f"; still nothing {args.widen_days} days further",
            )

    return AvailabilityResult(
        slots=slots,
        blocked=kept,
        appointment_type=appointment_type,
        rejection=rejection,
        widened=widened,
    )


# ---------------------------------------------------------------------------
# list_appointments: the only source of an appointment_id
# ---------------------------------------------------------------------------


def _remember(ctx: ToolContext, appointments: list[Appointment]) -> None:
    """Keep this call's appointments so ``prepare_*`` can verify an id it is handed.

    Per socket, in ``ctx.state``, JSON-safe. Never shared between calls.
    """
    seen = ctx.state.setdefault("diary_appointments", {})
    for item in appointments:
        seen[item.appointment_id] = item.model_dump(mode="json")


def _remembered(ctx: ToolContext, appointment_id: str) -> Appointment | None:
    raw = ctx.state.get("diary_appointments", {}).get(appointment_id)
    return Appointment.model_validate(raw) if raw else None


async def _appointments_of(ctx: ToolContext, patient_id: str) -> list[Appointment]:
    """One patient's whole diary, past and future, as the API reports it.

    Asking for ``all`` and splitting here keeps the answer anchored to
    ``ctx.now`` instead of to whatever clock the API filtered against.
    """
    try:
        items = await ctx.clinic.appointments(patient_id, when="all")
    except ClinicApiError:
        items = await ctx.clinic.appointments(patient_id)
    _remember(ctx, items)
    return items


async def list_appointments(ctx: ToolContext, args: ListAppointmentsInput) -> AppointmentList:
    """The patient's diary. ``upcoming`` is the only source of an appointment_id.

    Split against ``ctx.now``: an appointment is upcoming when it starts after
    the moment this call connected. A past visit's id is never an answer, so it
    must not be in the list the model sees when the caller says "my appointment".
    """
    items = await _appointments_of(ctx, args.patient_id)
    if args.when == "upcoming":
        items = [a for a in items if a.start > ctx.now and not _is_dead(a)]
    elif args.when == "past":
        items = [a for a in items if a.start <= ctx.now]
    return AppointmentList(appointments=sorted(items, key=lambda a: a.start))


def _is_dead(appointment: Appointment) -> bool:
    return (appointment.status or "").strip().lower().replace("-", "_") in _DEAD_STATUSES


async def _locate_appointment(
    ctx: ToolContext, appointment_id: str, patient_id: str | None
) -> Appointment | None:
    """The record behind an ``appointment_id``, from the API and nowhere else.

    In order: what this call has already read, the named patient's diary, the
    diary of whoever owns the line, and - offline or in a small directory - a
    bounded walk of the directory. ``prepare_reschedule`` gets no
    ``patient_id`` in the contract, which is why the last resorts exist.
    """
    known = _remembered(ctx, appointment_id)
    if known is not None:
        return known

    candidates: list[str] = [patient_id] if patient_id else []
    if ctx.from_number:
        try:
            for record in await ctx.clinic.directory(phone=ctx.from_number):
                candidates.append(record.patient_id)
        except ClinicApiError:
            pass
    for candidate in candidates:
        for item in await _appointments_of(ctx, candidate):
            if item.appointment_id == appointment_id:
                return item

    try:
        everyone = await ctx.clinic.directory()
    except ClinicApiError:
        return None
    for record in everyone[:_MAX_DIRECTORY_SCAN]:
        if record.patient_id in candidates:
            continue
        for item in await _appointments_of(ctx, record.patient_id):
            if item.appointment_id == appointment_id:
                return item
    return None


# ---------------------------------------------------------------------------
# prepare_*: the guards an action passes before it leaves
# ---------------------------------------------------------------------------


def _slot_rejection(
    ctx: ToolContext, catalogue: Catalogue, slot_start: datetime
) -> Rejection | None:
    """The calendar checks every booked or moved slot has to survive."""
    today = ctx.now.astimezone(MADRID).date()
    day = slot_start.astimezone(MADRID).date()
    if day <= today:
        return Rejection(
            reason="no_availability",
            detail=f"same-day booking: slot {day} is not after the call day {today}",
        )
    if catalogue.bookable_from and day < catalogue.bookable_from:
        return Rejection(
            reason="no_availability",
            detail=f"slot {day} is before the bookable window opens ({catalogue.bookable_from})",
        )
    if catalogue.bookable_to and day > catalogue.bookable_to:
        return Rejection(
            reason="no_availability",
            detail=f"slot {day} is after the bookable window closes ({catalogue.bookable_to})",
        )
    if day in catalogue.closure_days:
        return Rejection(reason="clinic_closed", detail=f"slot {day} falls on a closure day")
    return None


async def _fresh_availability(ctx: ToolContext, **query: object) -> AvailabilityResponse:
    """Use a client's live hook when its normal availability path is cached."""
    fresh = getattr(ctx.clinic, "fresh_availability", None)
    if fresh is not None:
        return await fresh(**query)
    return await ctx.clinic.availability(**query)  # type: ignore[arg-type]


async def prepare_booking(ctx: ToolContext, args: PrepareBookingInput) -> BookingResult:
    """Build the ``BookAction`` for a chosen slot, or reject it.

    Every id on the action is copied verbatim from the slot ``/availability``
    offered: ``provider_id``, ``location_id``, ``appointment_type_id`` and the
    ``slot`` timestamp itself. Nothing is renamed and nothing is rebuilt by
    hand - the API compares ids exactly, so a hand-made type id fails even
    when time and duration match.

    Guards before building the action:

    - Nothing is booked on the day of the call. "Earliest" starts tomorrow,
      measured against ``ctx.now`` in Europe/Madrid, never the machine clock.
    - The slot must sit inside the catalogue's bookable window and not on a
      closure day.
    - The exact slot (provider, location, type, start) must still appear in
      the availability answer for that day and patient. A slot that is not
      there was never offered, so booking it would report ids the clinic
      does not recognise.
    """
    catalogue = await ctx.clinic.catalogue()
    rejection = _slot_rejection(ctx, catalogue, args.slot.start)
    if rejection:
        return BookingResult(rejection=rejection)

    day = args.slot.start.astimezone(MADRID).date()
    try:
        availability = await _fresh_availability(
            ctx,
            date_from=day,
            date_to=day,
            provider_id=args.slot.provider_id,
            location_id=args.slot.location_id,
            patient_id=args.patient_id,
        )
    except ClinicApiError as exc:
        return BookingResult(
            rejection=Rejection(
                reason="no_availability",
                detail=f"availability re-check failed: {exc}",
            )
        )
    offered = any(
        slot.start == args.slot.start
        and slot.provider_id == args.slot.provider_id
        and slot.location_id == args.slot.location_id
        and slot.appointment_type_id == args.slot.appointment_type_id
        for slot in availability.slots
    )
    if not offered:
        return BookingResult(
            rejection=Rejection(
                reason="no_availability",
                detail=(
                    f"slot {args.slot.start.isoformat()} with provider "
                    f"{args.slot.provider_id} at {args.slot.location_id} "
                    f"({args.slot.appointment_type_id}) is not in the "
                    "availability answer for that day"
                ),
            )
        )

    return BookingResult(
        action=BookAction(
            patient_id=args.patient_id,
            provider_id=args.slot.provider_id,
            location_id=args.slot.location_id,
            appointment_type_id=args.slot.appointment_type_id,
            slot=args.slot.start,
            policy_id=args.policy_id,
        )
    )


async def _movable(
    ctx: ToolContext, appointment_id: str, patient_id: str | None
) -> tuple[Appointment | None, Rejection | None]:
    """The appointment an id names, when it may still be moved or cancelled.

    Three ways this fails, three different reasons: the id belongs to nobody we
    can read (``out_of_scope`` - it did not come from the API), it belongs to
    another patient (``caller_not_authorised``), or the visit is already over
    (``out_of_scope`` - a past id is never an answer).
    """
    found = await _locate_appointment(ctx, appointment_id, patient_id)
    if found is None:
        return None, Rejection(
            reason="out_of_scope",
            detail=(
                f"appointment {appointment_id} is in no diary this call has read; "
                "an appointment_id comes only from /patients/{id}/appointments"
            ),
        )
    if patient_id and found.patient_id != patient_id:
        return None, Rejection(
            reason="caller_not_authorised",
            detail=f"appointment {appointment_id} belongs to {found.patient_id}, not {patient_id}",
        )
    if found.start <= ctx.now:
        return None, Rejection(
            reason="out_of_scope",
            detail=(
                f"appointment {appointment_id} started {found.start.isoformat()}, "
                f"before the call ({ctx.now.isoformat()}): a past visit cannot be changed"
            ),
        )
    if _is_dead(found):
        return None, Rejection(
            reason="out_of_scope",
            detail=f"appointment {appointment_id} is {found.status}, not a live booking",
        )
    return found, None


async def prepare_reschedule(ctx: ToolContext, args: PrepareRescheduleInput) -> RescheduleResult:
    """Build the ``RescheduleAction``. A past visit cannot be moved.

    ``appointment_id`` must be one this call read from
    ``/patients/{id}/appointments`` and it must still be upcoming against
    ``ctx.now``. The new slot passes the same calendar guards as a booking.
    """
    appointment, rejection = await _movable(ctx, args.appointment_id, None)
    if rejection or appointment is None:
        return RescheduleResult(rejection=rejection)

    catalogue = await ctx.clinic.catalogue()
    slot_problem = _slot_rejection(ctx, catalogue, args.slot.start)
    if slot_problem:
        return RescheduleResult(rejection=slot_problem)

    return RescheduleResult(
        action=RescheduleAction(
            appointment_id=appointment.appointment_id,
            provider_id=args.slot.provider_id,
            location_id=args.slot.location_id,
            slot=args.slot.start,
            policy_id=args.policy_id,
        )
    )


async def prepare_cancel(ctx: ToolContext, args: PrepareCancelInput) -> CancelResult:
    """Build the ``CancelAction``. A past visit cannot be cancelled.

    Two cancellations in one call are two of these and two submissions; the
    guard is per appointment, so each one is checked against its own patient.
    """
    appointment, rejection = await _movable(ctx, args.appointment_id, args.patient_id)
    if rejection or appointment is None:
        return CancelResult(rejection=rejection)
    return CancelResult(action=CancelAction(appointment_id=appointment.appointment_id))
