"""Read-only client for the clinic API (Clínica Arenal).

Two implementations share one interface:

- ``ClinicClient``     - live HTTP, authenticated with ``X-Api-Key``.
- ``FakeClinicClient`` - in-memory fixtures, no network. Used when no key is set.

The catalogue never changes during the event. ``ClinicClient`` fetches it once
and keeps it for the life of the process. Patient lookups are never cached.

Every path, query parameter and field name below is taken from
``docs/platform/openapi.json`` and was checked against live responses from all
nine read-only routes on 18 Sep 2026. ``tests/test_openapi_alignment.py``
re-checks the submit side against that schema on every run.

The ``_adapt_*`` functions are the only place a platform field name appears.
Everything above them speaks ``vortex.contract``.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from typing import Any, Literal, Protocol

import httpx

from vortex.clinic import fixtures
from vortex.contract import (
    ALL_REASONS,
    MADRID,
    Appointment,
    AppointmentTypeRecord,
    AvailabilityProvider,
    AvailabilityResponse,
    BlockedProvider,
    Catalogue,
    DeclineReason,
    LeaveRecord,
    OpeningHours,
    PatientRecord,
    ProviderSchedule,
    Slot,
)

#: ``AppointmentWindow`` in the platform schema; anything else is a 422.
AppointmentWindow = Literal["upcoming", "past", "all"]

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

#: The platform joins an interval's ends with an en dash ("09:00–14:00"). The
#: others are here so a plain hyphen could never cost us a whole catalogue.
_DASHES = ("–", "—", "-")

#: What ``new_patient_requirement`` can say. The platform uses the first two.
_NEW_PATIENT_REQUIREMENT = {
    "new_only": True,
    "new": True,
    "existing_only": False,
    "existing": False,
    "returning_only": False,
    "any": None,
    "": None,
}


def _adapt_slot(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "start": raw["start_time"],
        "provider_id": raw["provider_id"],
        "provider_name": raw.get("provider_name", ""),
        "specialty_id": raw.get("specialty_id", ""),
        "location_id": raw["location_id"],
        "appointment_type_id": raw["appointment_type_id"],
        "duration_minutes": raw["duration_minutes"],
        "payable_with": raw.get("payable_with") or [],
    }


def _adapt_appointment_type(raw: dict[str, Any]) -> dict[str, Any]:
    requirement = raw.get("new_patient_requirement") or ""
    return {
        "appointment_type_id": raw["id"],
        "name": raw["name"],
        "specialty_id": raw.get("specialty_id"),
        "duration_minutes": raw["duration_minutes"],
        "new_patient_requirement": requirement,
        "for_new_patients": _NEW_PATIENT_REQUIREMENT.get(requirement),
        "guidance": raw.get("guidance", ""),
    }


def restriction_reason(restriction: str) -> DeclineReason:
    """The decline reason a restriction id names.

    The platform's eleven restriction ids *are* the first eleven reasons, so
    this is a pass-through. It exists for the day it stops being one: an
    unknown rule must not raise in the middle of a call, because a call that
    submits nothing scores the same as a crash.
    """
    return restriction if restriction in ALL_REASONS else "out_of_scope"  # type: ignore[return-value]


def _adapt_blocked(raw: dict[str, Any]) -> dict[str, Any]:
    restriction = raw.get("restriction", "")
    reason = restriction_reason(restriction)
    return {
        "provider_id": raw["provider_id"],
        "reason": reason,
        "restriction": restriction,
        "detail": "" if reason == restriction else f"unmapped restriction {restriction!r}",
    }


def _adapt_appointment(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "appointment_id": raw["appointment_id"],
        "patient_id": raw["patient_id"],
        "provider_id": raw["provider_id"],
        "location_id": raw["location_id"],
        "appointment_type_id": raw["appointment_type_id"],
        "start": raw["start_time"],
        "duration_minutes": raw["duration_minutes"],
    }


def _adapt_availability_provider(raw: dict[str, Any]) -> dict[str, Any]:
    """``ProviderOut``: leaner than the catalogue's provider, and its
    ``locations`` and ``accepted_insurers`` are ids, not names."""
    return {
        "provider_id": raw["id"],
        "name": raw.get("name", ""),
        "specialty_id": raw.get("specialty_id", ""),
        "languages": raw.get("languages", []),
        "insurer_ids_accepted": raw.get("accepted_insurers", []),
        "location_ids": raw.get("locations", []),
        "on_leave_until": raw.get("on_leave_until") or "",
    }


def _split_interval(interval: str) -> tuple[time, time] | None:
    for dash in _DASHES:
        opens_s, sep, closes_s = interval.partition(dash)
        if sep:
            try:
                return time.fromisoformat(opens_s.strip()), time.fromisoformat(closes_s.strip())
            except ValueError:
                return None
    return None


def _adapt_hours(raw_hours: list[dict[str, Any]]) -> list[OpeningHours]:
    """One ``OpeningHours`` per interval; a lunch-closed day yields two."""
    hours: list[OpeningHours] = []
    for day in raw_hours:
        name = str(day.get("weekday", "")).strip().lower()
        if name not in WEEKDAYS:
            continue
        weekday = WEEKDAYS.index(name)
        for interval in day.get("intervals", []):
            parsed = _split_interval(interval)
            if parsed is None:
                continue
            hours.append(OpeningHours(weekday=weekday, opens=parsed[0], closes=parsed[1]))
    return hours


def _adapt_catalogue(raw: dict[str, Any]) -> dict[str, Any]:
    """Raw ``GET /api/v1/clinic`` -> the shape ``Catalogue`` expects.

    The raw API cross-references providers, locations, specialties and
    appointment types by *name* (``provider_names``, ``covered_location_names``
    ...); the contract wants ids everywhere, because ids are what we submit.
    Build id lookups from each list's own ``id``/``name`` pair first, then
    rewrite every cross-reference through them.

    A provider's ``schedules`` carry a real ``location_id``, so where they exist
    they beat mapping ``location_names`` back through a lookup.
    """
    provider_by_name = {p["name"]: p["id"] for p in raw["providers"]}
    location_by_name = {loc["name"]: loc["id"] for loc in raw["locations"]}
    appt_type_by_name = {a["name"]: a["id"] for a in raw["appointment_types"]}
    specialty_by_name = {s["name"]: s["id"] for s in raw["specialties"]}

    def ids(names: list[str] | None, lookup: dict[str, str]) -> list[str]:
        """Names -> ids, keeping anything already an id (or newly unknown)."""
        return [lookup.get(n, n) for n in (names or [])]

    def insurer_ids(refs: list[dict[str, Any]] | None) -> list[str]:
        return [i["id"] for i in (refs or [])]

    providers = []
    for p in raw["providers"]:
        leave_raw = p.get("leave")
        schedules = [
            ProviderSchedule(
                location_id=sch["location_id"], hours=_adapt_hours(sch.get("days", []))
            )
            for sch in p.get("schedules", [])
        ]
        location_ids = [sch.location_id for sch in schedules] or ids(
            p.get("location_names"), location_by_name
        )
        providers.append(
            {
                "provider_id": p["id"],
                "name": p["name"],
                "specialty_id": p["specialty_id"],
                "specialty_name": p.get("specialty_name", ""),
                "languages": p.get("languages", []),
                "appointment_type_ids": ids(p.get("appointment_type_names"), appt_type_by_name),
                "location_ids": location_ids,
                "insurer_ids_accepted": insurer_ids(p.get("accepted_insurers")),
                "insurer_ids_refused": insurer_ids(p.get("refused_insurers")),
                "schedules": schedules,
                # The platform sends one leave period or null, never a list.
                "leave": (
                    [
                        LeaveRecord(
                            date_from=leave_raw["start"],
                            date_to=leave_raw["end"],
                            reason=leave_raw.get("reason", ""),
                        )
                    ]
                    if leave_raw
                    else []
                ),
            }
        )

    locations = []
    for loc in raw["locations"]:
        locations.append(
            {
                "location_id": loc["id"],
                "name": loc["name"],
                "address": loc.get("address", ""),
                "latitude": loc.get("latitude"),
                "longitude": loc.get("longitude"),
                "hours": _adapt_hours(loc.get("hours", [])),
                "provider_ids": ids(loc.get("provider_names"), provider_by_name),
                "insurer_ids": insurer_ids(loc.get("covered_by")),
                "insurer_ids_excluded": insurer_ids(loc.get("not_covered_by")),
            }
        )

    specialties = []
    for s in raw["specialties"]:
        specialties.append(
            {
                "specialty_id": s["id"],
                "name": s["name"],
                "min_age_months": s.get("min_age_months"),
                "max_age_months": s.get("max_age_months"),
                "referral_required": s.get("referral_required", False),
                "insurer_ids": insurer_ids(s.get("covered_by")),
                "insurer_ids_excluded": insurer_ids(s.get("not_covered_by")),
                "provider_ids": ids(s.get("provider_names"), provider_by_name),
            }
        )

    appointment_types = [_adapt_appointment_type(a) for a in raw["appointment_types"]]

    insurance_plans = []
    for pl in raw["plans"]:
        insurance_plans.append(
            {
                "insurer_id": pl["id"],
                "name": pl["name"],
                "specialty_ids": ids(pl.get("covered_specialty_names"), specialty_by_name),
                "specialty_ids_excluded": ids(
                    pl.get("uncovered_specialty_names"), specialty_by_name
                ),
                "location_ids": ids(pl.get("covered_location_names"), location_by_name),
                "location_ids_excluded": ids(pl.get("uncovered_location_names"), location_by_name),
                "provider_ids": ids(pl.get("accepted_by"), provider_by_name),
                "provider_ids_refused": ids(pl.get("refused_by"), provider_by_name),
                "holders": pl.get("holders"),
            }
        )

    # A restriction's id is the decline reason itself, so the rule that bit can
    # always be named. ``blocked[].restriction`` sends the same id back.
    restrictions = [
        {
            "rule_id": r["id"],
            "reason": restriction_reason(r["id"]),
            "description": r.get("title", ""),
            "explanation": r.get("explanation", ""),
        }
        for r in raw.get("restrictions", [])
    ]

    calendar = raw.get("calendar", {})
    return {
        "clinic_name": raw.get("clinic_name", ""),
        "patient_count": raw.get("patient_count"),
        "locations": locations,
        "providers": providers,
        "specialties": specialties,
        "appointment_types": appointment_types,
        "insurance_plans": insurance_plans,
        "restrictions": restrictions,
        "bookable_from": calendar.get("starts"),
        "bookable_to": calendar.get("ends"),
        "closure_days": calendar.get("closure_days", []),
        "max_span_days": calendar.get("max_span_days", 14),
        "slot_minutes": calendar.get("slot_minutes", 15),
    }


class ClinicApi(Protocol):
    """What every lane may call. One instance is safe to share across calls."""

    async def catalogue(self) -> Catalogue: ...

    async def directory(
        self,
        *,
        name: str | None = None,
        national_id: str | None = None,
        phone: str | None = None,
        date_of_birth: date | None = None,
    ) -> list[PatientRecord]: ...

    async def availability(
        self,
        *,
        date_from: date,
        date_to: date,
        provider_id: str | None = None,
        specialty_id: str | None = None,
        location_id: str | None = None,
        patient_id: str | None = None,
        insurer: list[str] | None = None,
    ) -> AvailabilityResponse: ...

    async def appointments(
        self, patient_id: str, *, when: AppointmentWindow = "upcoming"
    ) -> list[Appointment]: ...

    async def health(self) -> bool: ...

    async def aclose(self) -> None: ...


class ClinicApiError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"clinic api {status}: {detail}")
        self.status = status
        self.detail = detail


# ---------------------------------------------------------------------------
# The platform's own 422s, checked here first. Each one costs a round trip and
# arrives as an exception either way; raising locally keeps the two clients
# answering identically and keeps the reason readable.
# ---------------------------------------------------------------------------

APPOINTMENT_WINDOWS = ("upcoming", "past", "all")


def check_directory_query(
    name: str | None, national_id: str | None, phone: str | None, date_of_birth: date | None
) -> None:
    """A lone surname is a 422, not an empty result.

    The platform wants a name of at least a given name plus one surname, or an
    exact ``national_id``, ``phone`` or ``date_of_birth``.
    """
    if national_id or phone or date_of_birth:
        return
    if name and len(name.split()) >= 2:
        return
    raise ClinicApiError(
        422,
        "directory query needs a name (given name plus at least one surname) "
        "or an exact national_id, phone, or date_of_birth",
    )


def check_availability_query(
    date_from: date, date_to: date, provider_id: str | None, specialty_id: str | None
) -> None:
    if not provider_id and not specialty_id:
        raise ClinicApiError(422, "availability needs provider_id or specialty_id")
    if date_to < date_from:
        raise ClinicApiError(422, "date_to is before date_from")


def check_when(when: str) -> None:
    if when not in APPOINTMENT_WINDOWS:
        raise ClinicApiError(422, f"when must be one of {', '.join(APPOINTMENT_WINDOWS)}")


class ClinicClient:
    """Live client. Every request carries the team key."""

    def __init__(self, base_url: str, api_key: str, *, timeout: float = 10.0):
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-Api-Key": api_key},
            timeout=timeout,
        )
        self._catalogue: Catalogue | None = None
        self._catalogue_lock = asyncio.Lock()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        clean = {k: v for k, v in (params or {}).items() if v not in (None, "", [])}
        response = await self._http.get(path, params=clean)
        if response.status_code >= 400:
            raise ClinicApiError(response.status_code, response.text[:500])
        return response.json()

    async def health(self) -> bool:
        try:
            response = await self._http.get("/api/v1/health")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def catalogue(self) -> Catalogue:
        async with self._catalogue_lock:
            if self._catalogue is None:
                data = await self._get("/api/v1/clinic")
                self._catalogue = Catalogue.model_validate(_adapt_catalogue(data))
            return self._catalogue

    async def directory(
        self,
        *,
        name: str | None = None,
        national_id: str | None = None,
        phone: str | None = None,
        date_of_birth: date | None = None,
    ) -> list[PatientRecord]:
        check_directory_query(name, national_id, phone, date_of_birth)
        params = {
            "name": name,
            "national_id": national_id,
            "phone": phone,
            "date_of_birth": date_of_birth.isoformat() if date_of_birth else None,
        }
        data = await self._get("/api/v1/directory", params)
        items = data.get("matches", data) if isinstance(data, dict) else data
        # PatientMatchOut already speaks our field names, ``email`` apart: the
        # directory does not return one.
        return [PatientRecord.model_validate(item) for item in items]

    async def availability(
        self,
        *,
        date_from: date,
        date_to: date,
        provider_id: str | None = None,
        specialty_id: str | None = None,
        location_id: str | None = None,
        patient_id: str | None = None,
        insurer: list[str] | None = None,
    ) -> AvailabilityResponse:
        check_availability_query(date_from, date_to, provider_id, specialty_id)
        params: dict[str, Any] = {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "provider_id": provider_id,
            "specialty_id": specialty_id,
            "location_id": location_id,
            "patient_id": patient_id,
        }
        if insurer:
            params["insurer"] = insurer  # httpx repeats list params: ?insurer=a&insurer=b
        data = await self._get("/api/v1/availability", params)
        adapted = {
            "providers": [_adapt_availability_provider(p) for p in data.get("providers", [])],
            "slots": [_adapt_slot(s) for s in data.get("slots", [])],
            "blocked": [_adapt_blocked(b) for b in data.get("blocked", [])],
            "appointment_type": (
                _adapt_appointment_type(data["appointment_type"])
                if data.get("appointment_type")
                else None
            ),
        }
        return AvailabilityResponse.model_validate(adapted)

    async def appointments(
        self, patient_id: str, *, when: AppointmentWindow = "upcoming"
    ) -> list[Appointment]:
        check_when(when)
        data = await self._get(f"/api/v1/patients/{patient_id}/appointments", {"when": when})
        items = data.get("appointments", data) if isinstance(data, dict) else data
        return [Appointment.model_validate(_adapt_appointment(item)) for item in items]

    async def aclose(self) -> None:
        await self._http.aclose()


def _digits9(phone: str) -> str:
    """Fold a phone to its nine national digits, like the API does."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    return digits[-9:]


class FakeClinicClient:
    """Offline client over ``fixtures``. Deterministic; no network.

    The fixtures are raw platform payloads, so they go through the same
    ``_adapt_*`` functions as a live response. That is the point: offline runs
    exercise the adapters, and a field name that only the platform knows about
    breaks a test here instead of a call there.
    """

    def __init__(self) -> None:
        self._catalogue = Catalogue.model_validate(_adapt_catalogue(fixtures.CLINIC))
        self._patients = [PatientRecord.model_validate(p) for p in fixtures.PATIENTS]
        self._appointments = [
            Appointment.model_validate(_adapt_appointment(a)) for a in fixtures.APPOINTMENTS
        ]

    async def health(self) -> bool:
        return True

    async def catalogue(self) -> Catalogue:
        return self._catalogue

    async def directory(
        self,
        *,
        name: str | None = None,
        national_id: str | None = None,
        phone: str | None = None,
        date_of_birth: date | None = None,
    ) -> list[PatientRecord]:
        # NOT enforcing ``check_directory_query`` here is deliberate, and it is
        # the one place this client is more permissive than the platform: a
        # parameter-less ``directory()`` is answered with the whole set offline
        # and with a 422 live.
        #
        # ``rules._patient()`` used to rely on that, so every rule read off the
        # record (age, referral, allowance) stood down on a live call while the
        # offline suite stayed green. It now looks a record up the way the
        # platform allows -- see ``vortex/rules/tools.py``.
        #
        # What still calls it bare is ``diary._find_appointment``'s last-resort
        # walk, which already catches the live 422 and whose contract leaves it
        # no ``patient_id`` to search on. Tightening this would turn that lane's
        # offline fallback off without giving it a replacement, so the
        # divergence stays, documented, until that lane picks it up.
        # Exact-field filter, like the live API: a field that does not match excludes.
        found = []
        for p in self._patients:
            if name and not _name_matches(name, p):
                continue
            if national_id and national_id.replace(" ", "").upper() != p.national_id.upper():
                continue
            if phone and _digits9(phone) != _digits9(p.phone):
                continue
            if date_of_birth and date_of_birth != p.date_of_birth:
                continue
            found.append(p)
        return found

    async def availability(
        self,
        *,
        date_from: date,
        date_to: date,
        provider_id: str | None = None,
        specialty_id: str | None = None,
        location_id: str | None = None,
        patient_id: str | None = None,
        insurer: list[str] | None = None,
    ) -> AvailabilityResponse:
        check_availability_query(date_from, date_to, provider_id, specialty_id)
        cat = self._catalogue
        if (date_to - date_from).days > cat.max_span_days:
            raise ClinicApiError(422, "date range cannot exceed 14 days")
        if (cat.bookable_from and date_from < cat.bookable_from) or (
            cat.bookable_to and date_to > cat.bookable_to
        ):
            raise ClinicApiError(422, "date range is outside the published calendar")
        providers = [
            p
            for p in cat.providers
            if (not provider_id or p.provider_id == provider_id)
            and (not specialty_id or p.specialty_id == specialty_id)
            and (not location_id or location_id in p.location_ids)
        ]
        patient = next((p for p in self._patients if p.patient_id == patient_id), None)
        spec = specialty_id or (providers[0].specialty_id if providers else None)
        appt_type = _pick_type(cat, spec, patient)
        # Like the platform: a slot is priced only against the plans the query
        # named, either explicitly or through the patient's own record.
        asked = list(insurer or []) or ([patient.insurer] if patient and patient.insurer else [])
        slots: list[Slot] = []
        blocked: list[BlockedProvider] = []
        # The plan rules the catalogue never publishes. Like the platform, a
        # provider they stop is named in ``blocked`` and offers no slot.
        for p in providers:
            restriction = _standing_restriction(p, patient, asked)
            if restriction:
                blocked.append(
                    BlockedProvider(
                        provider_id=p.provider_id,
                        reason=restriction_reason(restriction),
                        restriction=restriction,
                    )
                )
        providers = [
            p for p in providers if not any(b.provider_id == p.provider_id for b in blocked)
        ]
        day = date_from
        while day <= date_to:
            for p in providers:
                if any(lv.date_from <= day <= lv.date_to for lv in p.leave):
                    if not any(b.provider_id == p.provider_id for b in blocked):
                        blocked.append(
                            BlockedProvider(
                                provider_id=p.provider_id,
                                reason="provider_on_leave",
                                restriction="provider_on_leave",
                            )
                        )
                    continue
                for loc_id in p.location_ids:
                    loc = next(loc for loc in cat.locations if loc.location_id == loc_id)
                    if day in cat.closure_days:
                        continue
                    hours = next((h for h in loc.hours if h.weekday == day.weekday()), None)
                    if not hours:
                        continue
                    payable = [
                        i
                        for i in asked
                        if i in p.insurer_ids_accepted and i in (loc.insurer_ids or [i])
                    ]
                    slots.extend(
                        _fake_day_slots(
                            day, hours.opens, hours.closes, p, loc_id, appt_type, payable
                        )
                    )
            day = date.fromordinal(day.toordinal() + 1)
        return AvailabilityResponse(
            providers=[
                AvailabilityProvider(
                    provider_id=p.provider_id,
                    name=p.name,
                    specialty_id=p.specialty_id,
                    languages=p.languages,
                    insurer_ids_accepted=p.insurer_ids_accepted,
                    location_ids=p.location_ids,
                    on_leave_until=(
                        max(lv.date_to for lv in p.leave).isoformat() if p.leave else ""
                    ),
                )
                for p in providers
            ],
            slots=slots,
            blocked=blocked,
            appointment_type=appt_type,
        )

    async def appointments(
        self, patient_id: str, *, when: AppointmentWindow = "upcoming"
    ) -> list[Appointment]:
        check_when(when)
        now = datetime.now(tz=self._appointments[0].start.tzinfo) if self._appointments else None
        items = [a for a in self._appointments if a.patient_id == patient_id]
        if when == "upcoming":
            items = [a for a in items if now is None or a.start >= now]
        elif when == "past":
            items = [a for a in items if now is not None and a.start < now]
        return sorted(items, key=lambda a: a.start)

    async def aclose(self) -> None:
        return None


def _standing_restriction(
    provider: Any, patient: PatientRecord | None, asked: list[str]
) -> str | None:
    """The restriction id ``blocked`` would carry for this provider, if any.

    Reads ``fixtures.PLAN_REFERRALS`` and ``fixtures.EXHAUSTED_ALLOWANCES``,
    the two rules ``/clinic`` has no field for. A provider is stopped only when
    every plan the query is priced against stops them: a slot payable with
    another named plan is still a slot.
    """
    if not asked:
        return None
    held = {r.lower() for r in patient.referrals} if patient else set()
    found: list[str] = []
    for insurer in asked:
        hit = next(
            (
                r["restriction"]
                for r in fixtures.PLAN_REFERRALS
                if r["insurer"] == insurer
                and r["specialty_id"] == provider.specialty_id
                and provider.specialty_id not in held
            ),
            None,
        )
        if hit is None and patient is not None:
            hit = next(
                (
                    r["restriction"]
                    for r in fixtures.EXHAUSTED_ALLOWANCES
                    if r["insurer"] == insurer and r["patient_id"] == patient.patient_id
                ),
                None,
            )
        if hit is None:
            return None
        found.append(hit)
    return found[0]


def _name_matches(spoken: str, patient: PatientRecord) -> bool:
    tokens = {t.lower() for t in spoken.replace(",", " ").split()}
    record = {t.lower() for t in patient.full_name.split()}
    return tokens.issubset(record)


def _pick_type(
    cat: Catalogue, specialty_id: str | None, patient: PatientRecord | None
) -> AppointmentTypeRecord | None:
    """The one type that fits: specialty-specific wins over universal."""
    new = not (patient and patient.has_visited_before)
    own = [t for t in cat.appointment_types if t.specialty_id == specialty_id]
    universal = [t for t in cat.appointment_types if t.specialty_id is None]
    for pool in (own, universal):
        for t in pool:
            if t.for_new_patients is None or t.for_new_patients == new:
                return t
    return None


def _fake_day_slots(
    day: date,
    opens: time,
    closes: time,
    provider: Any,
    location_id: str,
    appt_type: AppointmentTypeRecord | None,
    payable_with: list[str] | None = None,
) -> list[Slot]:
    """Every third 15-minute step is free. Deterministic per provider."""
    slots: list[Slot] = []
    step = 0
    seed = sum(ord(c) for c in provider.provider_id)
    t = datetime.combine(day, opens, tzinfo=MADRID)
    end = datetime.combine(day, closes, tzinfo=MADRID)
    while t < end:
        if (step + seed) % 3 == 0:
            slots.append(
                Slot(
                    start=t,
                    provider_id=provider.provider_id,
                    provider_name=provider.name,
                    specialty_id=provider.specialty_id,
                    location_id=location_id,
                    appointment_type_id=appt_type.appointment_type_id if appt_type else "review",
                    duration_minutes=appt_type.duration_minutes if appt_type else 15,
                    payable_with=list(payable_with or []),
                )
            )
        t += timedelta(minutes=15)
        step += 1
    return slots
