"""What the clinic can be asked about itself (problem 16).

The caller asks before they commit — which site opens on a Saturday, is there a
clinic in Getafe, which dermatologist sits at Arenal Centro, which sites see
children — and then books on the answer. It is scored through the booking, so a
wrong answer is a wrong booking: say Norte opens on Saturday and the caller
asks for Norte on Saturday, which cannot be booked, and the case is lost.

Every answer here is read off the catalogue. Nothing is phrased as a guess, and
anything the catalogue does not publish is *not* answered — in particular the
weekdays an individual doctor consults, which is a property of their diary and
only ``/availability`` knows it. ``consulting_weekdays`` derives that from real
slots when the caller has asked for it.

The ``clinic_facts`` tool is the consumer: ``answer()`` turns one question into
a typed ``ClinicFacts`` the model reads back and then books against. The prompt
carries no site facts of its own, so the only way to say "Centro opens on
Saturday" is to have asked the catalogue. ``fact_sheet()`` renders the same
data as prose for a screen or a log; it is not sent to the model.
"""

from __future__ import annotations

from datetime import date

from vortex.contract import (
    WEEKDAY_IDS,
    AvailabilityResponse,
    Catalogue,
    ClinicFacts,
    ClinicFactsInput,
    LocationRecord,
    ProviderFact,
    ProviderRecord,
    Rejection,
    SiteFact,
    SpecialtyRecord,
)

WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def open_weekdays(site: LocationRecord) -> list[int]:
    """The weekdays a site takes appointments, Monday = 0."""
    return sorted({hours.weekday for hours in site.hours})


def opens_on(site: LocationRecord, weekday: int) -> bool:
    return weekday in open_weekdays(site)


def saturday_sites(catalogue: Catalogue) -> list[LocationRecord]:
    """Answers "which of your clinics is open on a Saturday?" — exactly these."""
    return [site for site in catalogue.locations if opens_on(site, 5)]


def sites_for_specialty(catalogue: Catalogue, specialty_id: str) -> list[LocationRecord]:
    """Answers "which of your clinics see children?" — the sites with somebody there."""
    hosts = {
        loc_id
        for provider in catalogue.providers
        if provider.specialty_id == specialty_id
        for loc_id in provider.location_ids
    }
    return [site for site in catalogue.locations if site.location_id in hosts]


def providers_at(
    catalogue: Catalogue, location_id: str, specialty_id: str | None = None
) -> list[ProviderRecord]:
    """Answers "which dermatologist consults at Arenal Centro?" — by site, by specialty."""
    return [
        provider
        for provider in catalogue.providers
        if location_id in provider.location_ids
        and (specialty_id is None or provider.specialty_id == specialty_id)
    ]


def providers_in_specialty(catalogue: Catalogue, specialty_id: str) -> list[ProviderRecord]:
    """Answers "how many orthopaedic surgeons do you have?" — len() of this."""
    return [p for p in catalogue.providers if p.specialty_id == specialty_id]


def site_by_town(catalogue: Catalogue, town: str) -> LocationRecord | None:
    """Answers "do you have a clinic in Getafe?" — matched on the published address."""
    wanted = town.strip().lower()
    for site in catalogue.locations:
        if wanted and (wanted in site.address.lower() or wanted in site.name.lower()):
            return site
    return None


def consulting_weekdays(availability: AvailabilityResponse, provider_id: str) -> list[int]:
    """Which weekdays a doctor actually has slots on, from real availability.

    The catalogue says where a doctor sits, never when. Answering "which days
    is she there?" from site opening hours would invent a day the caller then
    asks to book, so this reads it off the slots the clinic returned. Pass an
    ``/availability`` response covering a full week.
    """
    return sorted(
        {slot.start.weekday() for slot in availability.slots if slot.provider_id == provider_id}
    )


def _provider_fact(provider: ProviderRecord, today: date) -> ProviderFact:
    away = next((lv for lv in provider.leave if lv.date_from <= today <= lv.date_to), None)
    return ProviderFact(
        provider_id=provider.provider_id,
        name=provider.name,
        specialty_id=provider.specialty_id,
        location_ids=list(provider.location_ids),
        on_leave_until=away.date_to if away else None,
    )


def _site_fact(
    catalogue: Catalogue, site: LocationRecord, specialty_id: str | None, today: date
) -> SiteFact:
    return SiteFact(
        location_id=site.location_id,
        name=site.name,
        address=site.address,
        open_days=[WEEKDAY_IDS[day] for day in open_weekdays(site)],
        hours=sorted(site.hours, key=lambda h: (h.weekday, h.opens)),
        providers=[
            _provider_fact(p, today)
            for p in providers_at(catalogue, site.location_id, specialty_id)
        ],
    )


def answer(catalogue: Catalogue, args: ClinicFactsInput, today: date) -> ClinicFacts:
    """One catalogue question, answered as typed data.

    Each filter the caller gave narrows the sites: the one they named, the town
    they said, the specialty they want, the day they can come. What is left is
    the answer, with the people who sit at each site. Nothing is inferred: a
    site is "open on Saturday" only if the catalogue lists Saturday hours for
    it, and a doctor is "at Norte" only if their schedule says so.

    The rejection is for the two filters that name a rule when they empty the
    list: no site opens that day (``clinic_closed``) and no site has anybody in
    that specialty (``type_not_offered``). A town or a site id that matches
    nothing is simply an empty answer - no rule bit, the caller picks another.
    """
    sites = list(catalogue.locations)
    if args.location_id:
        sites = [s for s in sites if s.location_id == args.location_id]
    if args.town:
        found = site_by_town(catalogue, args.town)
        sites = [s for s in sites if found is not None and s.location_id == found.location_id]
    rejection: Rejection | None = None
    if args.specialty_id:
        serving = {s.location_id for s in sites_for_specialty(catalogue, args.specialty_id)}
        sites = [s for s in sites if s.location_id in serving]
        if not sites and not serving:
            rejection = Rejection(
                reason="type_not_offered",
                detail=f"no site has anybody in {args.specialty_id}",
            )
    if args.weekday:
        weekday = WEEKDAY_IDS.index(args.weekday)
        sites = [s for s in sites if opens_on(s, weekday)]
        if not sites and rejection is None:
            rejection = Rejection(
                reason="clinic_closed",
                detail=f"no site matching the question opens on a {args.weekday}",
            )
    return ClinicFacts(
        sites=[_site_fact(catalogue, s, args.specialty_id, today) for s in sites],
        closure_days=list(catalogue.closure_days),
        rejection=rejection,
    )


def _hours_text(site: LocationRecord) -> str:
    """Renders "Mon 09:00-20:00, ..." from the hours the site publishes."""
    by_day: dict[int, list[str]] = {}
    for hours in sorted(site.hours, key=lambda h: (h.weekday, h.opens)):
        span = f"{hours.opens:%H:%M}-{hours.closes:%H:%M}"
        by_day.setdefault(hours.weekday, []).append(span)
    return ", ".join(
        f"{WEEKDAY_NAMES[day][:3]} {'/'.join(spans)}" for day, spans in sorted(by_day.items())
    )


def _age_text(specialty: SpecialtyRecord) -> str:
    low, high = specialty.min_age_months, specialty.max_age_months
    if low is None and high is None:
        return "any age"
    if high is not None and low is None:
        return f"under {high // 12 + 1}s"
    if low is not None and high is None:
        return f"{low // 12} and over"
    return f"{low // 12}-{high // 12}"


def fact_sheet(catalogue: Catalogue) -> str:
    """The catalogue, compact enough for a system prompt.

    Only what the caller can ask about before they commit, and only what the
    catalogue actually publishes. Site opening hours are a site fact and belong
    here; the weekdays a named doctor consults are a diary fact and do not —
    ``find_slots`` answers those.
    """
    lines: list[str] = ["CLINIC FACTS (answer questions from this; never invent one)."]

    lines.append("Sites:")
    for site in catalogue.locations:
        lines.append(f"- {site.name} ({site.location_id}) — {site.address}. {_hours_text(site)}")
    saturdays = saturday_sites(catalogue)
    lines.append(
        "Open on Saturday: "
        + (", ".join(s.name for s in saturdays) if saturdays else "no site")
        + ". No site opens on a Sunday."
    )
    if catalogue.closure_days:
        lines.append(
            "Closed network-wide: " + ", ".join(day.isoformat() for day in catalogue.closure_days)
        )

    lines.append("Specialties:")
    for specialty in catalogue.specialties:
        sites = sites_for_specialty(catalogue, specialty.specialty_id)
        referral = ", referral required" if specialty.referral_required else ""
        lines.append(
            f"- {specialty.name} ({specialty.specialty_id}): {_age_text(specialty)}{referral}. "
            f"At {', '.join(s.name for s in sites) if sites else 'no site'}."
        )

    lines.append("Doctors:")
    for provider in catalogue.providers:
        sites = [
            site.name for site in catalogue.locations if site.location_id in provider.location_ids
        ]
        lines.append(
            f"- {provider.name} — {provider.specialty_id} at {', '.join(sites) or 'no site'}"
        )
    lines.append(
        "The days a named doctor consults are not listed here: check find_slots before naming one."
    )
    return "\n".join(lines)
