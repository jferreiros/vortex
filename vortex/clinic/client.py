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
    PatientRecord,
    Slot,
)


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
                self._catalogue = Catalogue.model_validate(data)
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
        items = data.get("patients", data) if isinstance(data, dict) else data
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
        return AvailabilityResponse.model_validate(data)

    async def appointments(self, patient_id: str, *, when: str = "upcoming") -> list[Appointment]:
        data = await self._get(f"/api/v1/patients/{patient_id}/appointments", {"when": when})
        items = data.get("appointments", data) if isinstance(data, dict) else data
        return [Appointment.model_validate(item) for item in items]

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
