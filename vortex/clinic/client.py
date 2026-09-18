"""Read-only client for the clinic API (Clínica Arenal).

Two implementations share one interface:

- ``ClinicClient``     - live HTTP, authenticated with ``X-Api-Key``.
- ``FakeClinicClient`` - in-memory fixtures, no network. Used when no key is set.

The catalogue never changes during the event. ``ClinicClient`` fetches it once
and keeps it for the life of the process. Patient lookups are never cached.

TODO(clinic): verify every path and query parameter against /api/openapi.json
as soon as the desk hands over a key. The paths below come from the docs; the
field names come from the docs' prose, not from a schema.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from typing import Any, Protocol

import httpx

from vortex.clinic import fixtures
from vortex.contract import (
    MADRID,
    Appointment,
    AppointmentTypeRecord,
    AvailabilityResponse,
    BlockedProvider,
    Catalogue,
    LeaveRecord,
    OpeningHours,
    PatientRecord,
    Slot,
)

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _adapt_slot(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "start": raw["start_time"],
        "provider_id": raw["provider_id"],
        "location_id": raw["location_id"],
        "appointment_type_id": raw["appointment_type_id"],
        "duration_minutes": raw["duration_minutes"],
    }


def _adapt_appointment_type(raw: dict[str, Any]) -> dict[str, Any]:
    requirement = raw.get("new_patient_requirement")
    for_new = {"new_only": True, "existing_only": False}.get(requirement)
    return {
        "appointment_type_id": raw["id"],
        "name": raw["name"],
        "specialty_id": raw.get("specialty_id"),
        "duration_minutes": raw["duration_minutes"],
        "for_new_patients": for_new,
        "guidance": raw.get("guidance", ""),
    }


def _adapt_blocked(raw: dict[str, Any]) -> dict[str, Any]:
    return {"provider_id": raw["provider_id"], "reason": raw["restriction"]}


def _adapt_appointment(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "appointment_id": raw["appointment_id"],
        "patient_id": raw["patient_id"],
        "provider_id": raw["provider_id"],
        "location_id": raw["location_id"],
        "appointment_type_id": raw["appointment_type_id"],
        "start": raw["start_time"],
    }


def _adapt_hours(raw_hours: list[dict[str, Any]]) -> list[OpeningHours]:
    """One ``OpeningHours`` per interval; a lunch-closed day yields two."""
    hours: list[OpeningHours] = []
    for day in raw_hours:
        weekday = WEEKDAYS.index(day["weekday"].lower())
        for interval in day["intervals"]:
            opens_s, closes_s = interval.split("–")
            hours.append(
                OpeningHours(
                    weekday=weekday,
                    opens=time.fromisoformat(opens_s.strip()),
                    closes=time.fromisoformat(closes_s.strip()),
                )
            )
    return hours


def _adapt_catalogue(raw: dict[str, Any]) -> dict[str, Any]:
    """Raw ``GET /api/v1/clinic`` -> the shape ``Catalogue`` expects.

    The raw API cross-references providers/locations/appointment types by
    *name*; the contract wants ids. Build id lookups from each list's own
    ``id``/``name`` pair first, then rewrite every cross-reference through them.
    """
    provider_by_name = {p["name"]: p["id"] for p in raw["providers"]}
    location_by_name = {loc["name"]: loc["id"] for loc in raw["locations"]}
    appt_type_by_name = {a["name"]: a["id"] for a in raw["appointment_types"]}
    specialty_by_name = {s["name"]: s["id"] for s in raw["specialties"]}

    providers = []
    for p in raw["providers"]:
        leave_raw = p.get("leave")
        providers.append(
            {
                "provider_id": p["id"],
                "name": p["name"],
                "specialty_id": p["specialty_id"],
                "languages": p.get("languages", []),
                "appointment_type_ids": [
                    appt_type_by_name.get(n, n) for n in p.get("appointment_type_names", [])
                ],
                "location_ids": [location_by_name.get(n, n) for n in p.get("location_names", [])],
                "insurer_ids_accepted": [i["id"] for i in p.get("accepted_insurers", [])],
                "insurer_ids_refused": [i["id"] for i in p.get("refused_insurers", [])],
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
                "provider_ids": [provider_by_name.get(n, n) for n in loc.get("provider_names", [])],
                "insurer_ids": [i["id"] for i in loc.get("covered_by", [])],
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
                "insurer_ids": [i["id"] for i in s.get("covered_by", [])],
            }
        )

    appointment_types = [_adapt_appointment_type(a) for a in raw["appointment_types"]]

    insurance_plans = []
    for pl in raw["plans"]:
        insurance_plans.append(
            {
                "insurer_id": pl["id"],
                "name": pl["name"],
                "specialty_ids": [
                    specialty_by_name.get(n, n) for n in pl.get("covered_specialty_names", [])
                ],
                "location_ids": [
                    location_by_name.get(n, n) for n in pl.get("covered_location_names", [])
                ],
                "provider_ids": [provider_by_name.get(n, n) for n in pl.get("accepted_by", [])],
            }
        )

    restrictions = [
        {"rule_id": r["id"], "reason": r["id"], "description": r["title"]}
        for r in raw.get("restrictions", [])
    ]

    calendar = raw.get("calendar", {})
    return {
        "locations": locations,
        "providers": providers,
        "specialties": specialties,
        "appointment_types": appointment_types,
        "insurance_plans": insurance_plans,
        "restrictions": restrictions,
        "bookable_from": calendar.get("starts"),
        "bookable_to": calendar.get("ends"),
        "closure_days": calendar.get("closure_days", []),
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
        self, patient_id: str, *, when: str = "upcoming"
    ) -> list[Appointment]: ...

    async def health(self) -> bool: ...

    async def aclose(self) -> None: ...


class ClinicApiError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"clinic api {status}: {detail}")
        self.status = status
        self.detail = detail


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
        params = {
            "name": name,
            "national_id": national_id,
            "phone": phone,
            "date_of_birth": date_of_birth.isoformat() if date_of_birth else None,
        }
        data = await self._get("/api/v1/directory", params)
        items = data.get("matches", data) if isinstance(data, dict) else data
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
            "slots": [_adapt_slot(s) for s in data.get("slots", [])],
            "blocked": [_adapt_blocked(b) for b in data.get("blocked", [])],
            "appointment_type": (
                _adapt_appointment_type(data["appointment_type"])
                if data.get("appointment_type")
                else None
            ),
        }
        return AvailabilityResponse.model_validate(adapted)

    async def appointments(self, patient_id: str, *, when: str = "upcoming") -> list[Appointment]:
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
    """Offline client over ``fixtures``. Deterministic; no network."""

    def __init__(self) -> None:
        self._catalogue = Catalogue.model_validate(fixtures.CLINIC)
        self._patients = [PatientRecord.model_validate(p) for p in fixtures.PATIENTS]
        self._appointments = [Appointment.model_validate(a) for a in fixtures.APPOINTMENTS]

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
        if (date_to - date_from).days > 14:
            raise ClinicApiError(422, "span longer than 14 days")
        cat = self._catalogue
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
        slots: list[Slot] = []
        blocked: list[BlockedProvider] = []
        day = date_from
        while day <= date_to:
            for p in providers:
                if any(lv.date_from <= day <= lv.date_to for lv in p.leave):
                    if not any(b.provider_id == p.provider_id for b in blocked):
                        blocked.append(
                            BlockedProvider(provider_id=p.provider_id, reason="provider_on_leave")
                        )
                    continue
                for loc_id in p.location_ids:
                    loc = next(loc for loc in cat.locations if loc.location_id == loc_id)
                    if day in cat.closure_days:
                        continue
                    hours = next((h for h in loc.hours if h.weekday == day.weekday()), None)
                    if not hours:
                        continue
                    slots.extend(
                        _fake_day_slots(day, hours.opens, hours.closes, p, loc_id, appt_type)
                    )
            day = date.fromordinal(day.toordinal() + 1)
        return AvailabilityResponse(slots=slots, blocked=blocked, appointment_type=appt_type)

    async def appointments(self, patient_id: str, *, when: str = "upcoming") -> list[Appointment]:
        now = datetime.now(tz=self._appointments[0].start.tzinfo) if self._appointments else None
        items = [a for a in self._appointments if a.patient_id == patient_id]
        if when == "upcoming":
            items = [a for a in items if now is None or a.start >= now]
        elif when == "past":
            items = [a for a in items if now is not None and a.start < now]
        return sorted(items, key=lambda a: a.start)

    async def aclose(self) -> None:
        return None


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
                    location_id=location_id,
                    appointment_type_id=appt_type.appointment_type_id if appt_type else "review",
                    duration_minutes=appt_type.duration_minutes if appt_type else 15,
                )
            )
        t += timedelta(minutes=15)
        step += 1
    return slots
