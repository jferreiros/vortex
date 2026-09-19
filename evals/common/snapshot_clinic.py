"""The frozen real clinic: ``FakeClinicClient``'s interface over the snapshot.

``evals/corpus/world/`` holds the real clinic taken by ``make evals-snapshot``:
the catalogue, every persona's directory record, the named patients' diaries
and the availability windows the published answers were drawn from. This client
answers from those files, so a replay run exercises the real ids, the real
slots and the real refusal rules while staying offline and free.

The snapshot stores adapted payloads — whatever ``ClinicClient`` would have
returned — so every answer validates straight into the ``vortex.contract``
records. The one deviation from the live API is deliberate: a lookup the
snapshot never took (an unknown patient, an unrecorded (patient, specialty,
policy) pair) answers empty rather than raising, so an invented id or a
forgotten ``patient_id`` surfaces as ``no_availability`` in the agent's own
words instead of as a harness crash.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from evals.corpus.catalogue import Case
from vortex.clinic.client import AppointmentWindow, check_availability_query, check_when
from vortex.contract import (
    MADRID,
    Appointment,
    AppointmentTypeRecord,
    AvailabilityProvider,
    AvailabilityResponse,
    BlockedProvider,
    Catalogue,
    PatientRecord,
    Slot,
)

WORLD_DIR = Path(__file__).resolve().parents[1] / "corpus" / "world"


def _digits9(phone: str) -> str:
    """Fold a phone to its nine national digits, like the API does."""
    return "".join(ch for ch in phone if ch.isdigit())[-9:]


def _name_matches(spoken: str, patient: PatientRecord) -> bool:
    tokens = {t.lower() for t in spoken.replace(",", " ").split()}
    record = {t.lower() for t in patient.full_name.split()}
    return tokens.issubset(record)


class SnapshotClinicClient:
    """Read-only clinic answered from ``evals/corpus/world/``. No network.

    Directory answers come from ``patients.json`` (the persona lookups the
    snapshot took, flattened to one record per patient), diaries from
    ``appointments.json``, and availability from
    ``availability-per-patient.json`` — the (patient, specialty, policy)
    windows the published answers need. A query without a ``patient_id``
    falls back to the per-specialty windows under ``availability/``, which
    are what the API serves before anyone is identified.
    """

    def __init__(self, world_dir: Path = WORLD_DIR) -> None:
        self._catalogue = Catalogue.model_validate(
            json.loads((world_dir / "catalogue.json").read_text())
        )
        per_patient = world_dir / "availability-per-patient.json"
        self._per_patient: dict[str, list[dict[str, Any]]] = (
            json.loads(per_patient.read_text()) if per_patient.exists() else {}
        )
        self._by_specialty: dict[str, list[dict[str, Any]]] = {}
        for path in sorted((world_dir / "availability").glob("*.json")):
            self._by_specialty[path.stem] = json.loads(path.read_text())
        charts = json.loads((world_dir / "patients.json").read_text())
        self._patients: dict[str, PatientRecord] = {}
        for chart in charts.values():
            for raw in chart.get("patients", []) if isinstance(chart, dict) else []:
                record = PatientRecord.model_validate(raw)
                self._patients.setdefault(record.patient_id, record)
        diaries = json.loads((world_dir / "appointments.json").read_text())
        self._diaries: dict[str, dict[str, list[Appointment]]] = {}
        for patient_id, windows in diaries.items():
            self._diaries[patient_id] = {
                when: [Appointment.model_validate(item) for item in items]
                for when, items in windows.items()
                if isinstance(items, list)
            }
        self._seed_diaries()

    # ---- ClinicApi ---------------------------------------------------------

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
        found = []
        for record in self._patients.values():
            if name and not _name_matches(name, record):
                continue
            if national_id and national_id.replace(" ", "").upper() != record.national_id.upper():
                continue
            if phone and _digits9(phone) != _digits9(record.phone):
                continue
            if date_of_birth and date_of_birth != record.date_of_birth:
                continue
            found.append(record)
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
        specialty = specialty_id or next(
            (p.specialty_id for p in cat.providers if p.provider_id == provider_id), None
        )
        # The first plan named on the call is the one the answer is priced
        # against; without one, the plan on the record — the snapshot's "" key.
        policy = next((i for i in (insurer or []) if i), "")
        windows = self._windows_for(patient_id, specialty, policy)

        slots: list[Slot] = []
        blocked: dict[str, BlockedProvider] = {}
        appointment_type: AppointmentTypeRecord | None = None
        for window in windows:
            if not _overlaps(window, date_from, date_to):
                continue
            response = window.get("response") or {}
            if appointment_type is None and response.get("appointment_type"):
                appointment_type = AppointmentTypeRecord.model_validate(
                    response["appointment_type"]
                )
            for raw in response.get("slots", []):
                start = datetime.fromisoformat(raw["start"])
                if not date_from <= start.date() <= date_to:
                    continue
                if provider_id and raw["provider_id"] != provider_id:
                    continue
                if location_id and raw["location_id"] != location_id:
                    continue
                slots.append(Slot.model_validate(raw))
            for raw in response.get("blocked", []):
                entry = BlockedProvider.model_validate(raw)
                if provider_id and entry.provider_id != provider_id:
                    continue
                blocked.setdefault(entry.provider_id, entry)

        # The snapshot's slots carry no provider name or specialty; the
        # catalogue has both, and readback lines speak them.
        by_id = {p.provider_id: p for p in cat.providers}
        for slot in slots:
            provider = by_id.get(slot.provider_id)
            if provider is not None:
                slot.provider_name = provider.name
                slot.specialty_id = provider.specialty_id
        slots.sort(key=lambda s: (s.start, s.provider_id, s.location_id))
        in_scope = [
            p
            for p in cat.providers
            if (not provider_id or p.provider_id == provider_id)
            and (not specialty or p.specialty_id == specialty)
            and (not location_id or location_id in p.location_ids)
        ]
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
                        max((lv.date_to for lv in p.leave), default="").isoformat()
                        if p.leave
                        else ""
                    ),
                )
                for p in in_scope
            ],
            slots=slots,
            blocked=list(blocked.values()),
            appointment_type=appointment_type,
        )

    async def appointments(
        self, patient_id: str, *, when: AppointmentWindow = "upcoming"
    ) -> list[Appointment]:
        check_when(when)
        diary = self._diaries.get(patient_id, {})
        if when == "all":
            items = diary.get("upcoming", []) + diary.get("past", [])
        else:
            items = diary.get(when, [])
        return sorted(items, key=lambda a: a.start)

    async def aclose(self) -> None:
        return None

    # ---- windows -----------------------------------------------------------

    def _windows_for(
        self, patient_id: str | None, specialty: str | None, policy: str
    ) -> list[dict[str, Any]]:
        """The snapshot windows for this query, or [] when none was taken.

        An exact (patient, specialty, policy) window wins; a named plan the
        snapshot never priced falls back to the plan on the record, which is
        how the API prices when the query names nothing it knows.
        """
        if not specialty:
            return []
        if patient_id:
            base = f"{patient_id}:{specialty}"
            for key in (f"{base}:{policy}", f"{base}:"):
                if key in self._per_patient:
                    return self._per_patient[key]
            return []
        return self._by_specialty.get(specialty, [])

    # ---- the diaries the snapshot never pulled ------------------------------

    def _seed_diaries(self) -> None:
        """Rebuild the diaries a CANCEL or RESCHEDULE answer depends on.

        The snapshot pulled diaries only for patients a BOOK answer names:
        the cancel and reschedule routes take an ``appointment_id`` and no
        ``patient_id``, so their patients never made the manifest. The
        organisers' answer is still ground truth — this patient holds this
        appointment — so the missing entries are rebuilt from it. A
        reschedule answer carries provider, site and slot; a cancel answer
        names the id alone, and that entry gets a placeholder time that is
        never judged: the true details live only in the caller's own words.
        """
        from evals.corpus.catalogue import load as load_roster

        held = {
            (pid, a.appointment_id)
            for pid, diary in self._diaries.items()
            for a in diary.get("upcoming", []) + diary.get("past", [])
        }
        for case in load_roster().cases:
            extras = 0
            for alternative in case.acceptable:
                for action in alternative:
                    appointment_id = action.get("appointment_id")
                    if not appointment_id:
                        continue
                    patient_id = action.get("patient_id") or _persona_patient(self._patients, case)
                    if patient_id is None or (patient_id, appointment_id) in held:
                        continue
                    held.add((patient_id, appointment_id))
                    self._diaries.setdefault(patient_id, {"upcoming": [], "past": []})
                    diary = self._diaries[patient_id]
                    diary.setdefault("upcoming", []).append(
                        Appointment(
                            appointment_id=appointment_id,
                            patient_id=patient_id,
                            provider_id=action.get("provider_id", ""),
                            location_id=action.get("location_id", ""),
                            appointment_type_id="",
                            start=_placeholder_start(case, extras),
                            duration_minutes=15,
                        )
                    )
                    extras += 1


def _persona_patient(patients: dict[str, PatientRecord], case: Case) -> str | None:
    """The persona's own record, as the snapshot's directory lookup found it."""
    data = case.persona.get("data") or {}
    national_id = str(data.get("national_id", "")).upper()
    for record in patients.values():
        if national_id and record.national_id.upper() == national_id:
            return record.patient_id
    return None


def _placeholder_start(case: Case, index: int) -> datetime:
    """A stand-in time for an appointment whose true hour nothing publishes."""
    hour, minute = ((10, 0), (14, 30), (12, 15))[index % 3]
    day = case.now.astimezone(MADRID).date() + timedelta(days=7)
    return datetime.combine(day, time(hour, minute), tzinfo=MADRID)


def _overlaps(window: dict[str, Any], date_from: date, date_to: date) -> bool:
    """Whether a snapshot window's days intersect the queried range."""
    return (
        date.fromisoformat(str(window["from"])) <= date_to
        and date.fromisoformat(str(window["to"])) >= date_from
    )
