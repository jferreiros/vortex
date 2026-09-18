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

The conversation lane is the consumer: ``fact_sheet()`` renders the whole thing
compactly enough to sit in the system prompt for the length of a call.
"""

from __future__ import annotations

from vortex.contract import (
    AvailabilityResponse,
    Catalogue,
    LocationRecord,
    ProviderRecord,
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
