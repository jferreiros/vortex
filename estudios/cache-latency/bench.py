"""Cache vs. no-cache latency study for the vortex tool layer.

Measures, end to end, what each tool costs when its clinic data comes from:

- ``no_cache``      a fresh ``ClinicClient`` per call - every call pays TCP+TLS,
                    HTTP and JSON, and even the catalogue is re-fetched.
- ``current``       one shared ``ClinicClient`` - what production does today:
                    the catalogue is cached in-process, every directory,
                    availability and appointments query still goes to HTTP.
- ``full_memory``   ``FakeClinicClient`` - the lower bound: everything already
                    in local memory (what a warm snapshot cache buys).

The "API" side is a local server that speaks the platform's routes and serves
the repo's own raw fixtures (``vortex/clinic/fixtures.py``), so the HTTP,
serialization and adaptation costs are real and only the wide-area network and
the organisers' server-side work are absent. That absent part is measured
separately as the *network floor*: real HTTPS timings against the production
host (``/api/v1/health`` answers 200 without a key; data routes answer 403, so
their timings are a lower bound for an authenticated call).

With ``PLATFORM_API_KEY`` set and ``--live``, the ``no_cache`` and ``current``
scenarios additionally run against the production API and the cache build pulls
real bytes - rerun then to replace every ``local_api`` number with a live one.

    uv run python estudios/cache-latency/bench.py                 # offline study
    PLATFORM_API_KEY=... uv run python estudios/cache-latency/bench.py --live
    uv run python estudios/cache-latency/bench.py --no-network    # no WAN at all

Writes ``results.json`` next to this file and prints the tables the study
(README.md) is built from. Read-only against the platform: submit routes are
never touched live (the write-call reference below goes to the local server).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import tempfile
import threading
import time
from collections import Counter
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402

from evals.common.context import make_context  # noqa: E402
from vortex.clinic import fixtures  # noqa: E402
from vortex.clinic.client import (  # noqa: E402
    ClinicClient,
    FakeClinicClient,
    _adapt_catalogue,
)
from vortex.contract import MADRID, Catalogue, PatientRecord  # noqa: E402
from vortex.tools import TOOLS  # noqa: E402

PROD_BASE_URL = "https://hackspain.getprosperapp.com"

# ---------------------------------------------------------------------------
# Raw-payload helpers: contract models back to platform wire shape, so the
# local server can answer like the platform does.
# ---------------------------------------------------------------------------


def raw_slot(slot) -> dict:
    return {
        "start_time": slot.start.isoformat(),
        "provider_id": slot.provider_id,
        "provider_name": slot.provider_name,
        "specialty_id": slot.specialty_id,
        "location_id": slot.location_id,
        "appointment_type_id": slot.appointment_type_id,
        "duration_minutes": slot.duration_minutes,
        "payable_with": slot.payable_with,
    }


def raw_availability_provider(p) -> dict:
    return {
        "id": p.provider_id,
        "name": p.name,
        "specialty_id": p.specialty_id,
        "languages": p.languages,
        "accepted_insurers": p.insurer_ids_accepted,
        "locations": p.location_ids,
        "on_leave_until": p.on_leave_until or None,
    }


def raw_blocked(b) -> dict:
    return {"provider_id": b.provider_id, "restriction": b.restriction}


def raw_appointment_type(t) -> dict:
    if t is None:
        return None
    return {
        "id": t.appointment_type_id,
        "name": t.name,
        "specialty_id": t.specialty_id,
        "duration_minutes": t.duration_minutes,
        "new_patient_requirement": "",
        "guidance": t.guidance,
    }


# ---------------------------------------------------------------------------
# Local platform server: platform routes over the repo's raw fixtures.
# ---------------------------------------------------------------------------


class PlatformState:
    def __init__(self) -> None:
        self.fake = FakeClinicClient()
        self.requests: Counter[str] = Counter()
        self.bytes_out = 0
        self._avail_cache: dict[tuple, dict] = {}
        self._raw_patients = {p["patient_id"]: p for p in fixtures.PATIENTS}
        self._raw_appointments = {a["appointment_id"]: a for a in fixtures.APPOINTMENTS}

    async def directory(self, params: dict) -> list[dict]:
        query = {
            k: v
            for k, v in params.items()
            if k in ("name", "national_id", "phone", "date_of_birth") and v
        }
        if "date_of_birth" in query:
            query["date_of_birth"] = date.fromisoformat(query["date_of_birth"])
        found = await self.fake.directory(**query)
        return [self._raw_patients[p.patient_id] for p in found]

    async def availability(self, params: dict) -> dict:
        key = tuple(sorted((k, json.dumps(v, sort_keys=True)) for k, v in params.items()))
        if key not in self._avail_cache:
            query = {
                "date_from": date.fromisoformat(params["date_from"]),
                "date_to": date.fromisoformat(params["date_to"]),
                "provider_id": params.get("provider_id") or None,
                "specialty_id": params.get("specialty_id") or None,
                "location_id": params.get("location_id") or None,
                "patient_id": params.get("patient_id") or None,
                "insurer": params.get("insurer") or None,
            }
            response = await self.fake.availability(**query)
            self._avail_cache[key] = {
                "providers": [raw_availability_provider(p) for p in response.providers],
                "slots": [raw_slot(s) for s in response.slots],
                "blocked": [raw_blocked(b) for b in response.blocked],
                "appointment_type": raw_appointment_type(response.appointment_type),
            }
        return self._avail_cache[key]

    async def appointments(self, patient_id: str, when: str) -> list[dict]:
        found = await self.fake.appointments(patient_id, when=when)
        return [self._raw_appointments[a.appointment_id] for a in found]


def query_params(query: str) -> dict:
    return {k: v[0] if len(v) == 1 else v for k, v in parse_qs(query).items()}


async def route(state: PlatformState, method: str, path: str, params: dict) -> tuple[int, object]:
    """One platform request answered off the fixtures, counted in ``state``.

    The only routing table: the socket server and the in-process transport
    both answer through here, so both serve the same JSON and the same
    request accounting.
    """
    state.requests[f"{method} {path}"] += 1
    if method == "GET":
        if path == "/api/v1/health":
            return 200, {"status": "ok"}
        if path == "/api/v1/clinic":
            return 200, fixtures.CLINIC
        if path == "/api/v1/directory":
            return 200, {"matches": await state.directory(params)}
        if path == "/api/v1/availability":
            return 200, await state.availability(params)
        if path.startswith("/api/v1/patients/"):
            patient_id = path.split("/")[4]
            when = params.get("when", "upcoming")
            return 200, {"appointments": await state.appointments(patient_id, when)}
    elif method == "POST" and path.startswith("/api/v1/submit/"):
        return 200, {"status": "ok"}
    return 404, {"detail": "not found"}


def make_handler(state: PlatformState):
    class Handler(BaseHTTPRequestHandler):
        def _serve(self, method: str) -> None:
            url = urlparse(self.path)
            status, payload = asyncio.run(route(state, method, url.path, query_params(url.query)))
            body = json.dumps(payload).encode()
            state.bytes_out += len(body)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:  # quiet
            return

        def do_GET(self) -> None:
            self._serve("GET")

        def do_POST(self) -> None:
            self._serve("POST")

    return Handler


def in_process_transport(state: PlatformState) -> httpx.MockTransport:
    """The server's routes without the socket, for a ``ClinicClient`` that must
    run where no listener may be bound."""

    async def respond(request: httpx.Request) -> httpx.Response:
        params = query_params(request.url.query.decode())
        status, payload = await route(state, request.method, request.url.path, params)
        body = json.dumps(payload).encode()
        state.bytes_out += len(body)
        return httpx.Response(status, content=body, headers={"Content-Type": "application/json"})

    return httpx.MockTransport(respond)


def start_server() -> tuple[ThreadingHTTPServer, PlatformState, str]:
    state = PlatformState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, state, f"http://127.0.0.1:{server.server_port}"


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------


def pct(samples: list[float]) -> dict:
    if not samples:
        return {}
    ordered = sorted(samples)
    return {
        "n": len(samples),
        "min_ms": round(ordered[0], 3),
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 3),
        "max_ms": round(ordered[-1], 3),
        "mean_ms": round(statistics.fmean(ordered), 3),
    }


# ---------------------------------------------------------------------------
# Tool call recipes: realistic arguments over the fixtures.
# ---------------------------------------------------------------------------


#: A five-day window inside the event calendar, shared by the ``find_slots``
#: recipe and the warmup that feeds the booking ones.
FIND_SLOTS_WINDOW: dict[str, str] = {"date_from": "2026-09-21", "date_to": "2026-09-25"}

#: recipe -> {tool argument: key in ``resolve_inputs``}. Every clinic-side
#: identifier a recipe needs is listed here and nowhere else, so a scenario
#: only ever times ids its own client answered for.
RESOLVED_INPUTS: dict[str, dict[str, str]] = {
    "find_patient": {"phone": "phone"},
    "find_slots": {"specialty_id": "specialty_id"},
    "list_appointments": {"patient_id": "appointment_patient_id"},
    "prepare_booking": {"patient_id": "patient_id", "policy_id": "policy_id", "slot": "slot"},
    "prepare_reschedule": {
        "appointment_id": "appointment_id",
        "policy_id": "appointment_policy_id",
        "slot": "slot",
    },
    "prepare_cancel": {"appointment_id": "appointment_id", "patient_id": "appointment_patient_id"},
    "check_eligibility": {"patient_id": "patient_id", "specialty_id": "specialty_id"},
    "nearest_location": {"specialty_id": "specialty_id"},
    "find_provider": {"spoken_name": "provider_name"},
    "clinic_facts": {"location_id": "location_id"},
}


def tool_recipes() -> dict[str, dict]:
    """Realistic arguments per tool, with every clinic-side identifier left out:
    ``apply_resolved_inputs`` fills those from the client the scenario runs
    against, so a fixture id never reaches the production API."""
    return {
        "find_patient": {},
        "validate_national_id": {"value": fixtures.PATIENTS[0]["national_id"]},
        "build_registration": {
            "given_name": "Lucia",
            "first_surname": "Sanz",
            "second_surname": "Pinto",
            "national_id": "48064716Y",
            "date_of_birth": "1999-04-02",
            "phone": "600111222",
            "email": "lucia@example.com",
            "insurer": "mapfre",
        },
        "resolve_date": {"phrase": "next Tuesday"},
        "find_slots": dict(FIND_SLOTS_WINDOW),
        "list_appointments": {"when": "all"},
        "prepare_booking": {},
        "prepare_reschedule": {},
        "prepare_cancel": {},
        "check_eligibility": {},
        "triage": {"complaint": "knee pain since yesterday"},
        "nearest_location": {"address": "Calle de Alcala 1, Madrid"},
        "find_provider": {},
        "clinic_facts": {},
    }


async def warmup_slot(client, args: dict) -> dict:
    """One slot ``client`` is really offering, for the booking/reschedule recipes."""
    spec = TOOLS["find_slots"]
    with tempfile.TemporaryDirectory() as tmp:
        ctx = make_context(call_id="bench-warmup", log_dir=Path(tmp), clinic=client)
        result = await spec.fn(ctx, spec.input_model.model_validate(args))
    slots = getattr(result, "slots", None) or getattr(result, "results", None) or []
    if not slots:
        raise RuntimeError(f"warmup find_slots returned no slots for {args}")
    slot = slots[0]
    return {
        "start": slot.start.isoformat(),
        "provider_id": slot.provider_id,
        "provider_name": slot.provider_name,
        "specialty_id": slot.specialty_id,
        "location_id": slot.location_id,
        "appointment_type_id": slot.appointment_type_id,
        "duration_minutes": slot.duration_minutes,
        "payable_with": slot.payable_with,
    }


async def known_patient(client, raw: dict) -> PatientRecord | None:
    """The fixture patient ``raw`` as ``client``'s own directory returns it."""
    for field in ("phone", "national_id"):
        value = raw.get(field)
        if not value:
            continue
        try:
            matches = await client.directory(**{field: value})
        except Exception:
            continue  # this client does not answer that field
        if matches:
            return matches[0]
    return None


async def resolve_inputs(client) -> dict:
    """Every clinic-side recipe value, taken from ``client`` itself.

    Catalogue ids and the warmup slot come straight off the client. A patient
    cannot be invented - ``/directory`` only answers an exact field - so each
    fixture patient is offered to the client and the first one it recognises is
    used, plus the first upcoming appointment of the first recognised patient
    that has one. What stays unresolved excludes its recipes instead of timing
    an identifier this API would reject.
    """
    resolved: dict = {}
    catalogue = await client.catalogue()
    if catalogue.specialties:
        resolved["specialty_id"] = catalogue.specialties[0].specialty_id
    if catalogue.locations:
        resolved["location_id"] = catalogue.locations[0].location_id
    if catalogue.providers:
        resolved["provider_name"] = catalogue.providers[0].name

    slot_args = dict(FIND_SLOTS_WINDOW)
    if "specialty_id" in resolved:
        slot_args["specialty_id"] = resolved["specialty_id"]
    try:
        resolved["slot"] = await warmup_slot(client, slot_args)
    except Exception as exc:
        print(f"!! no warmup slot: {type(exc).__name__}: {exc}", file=sys.stderr)

    for raw in fixtures.PATIENTS:
        if "patient_id" in resolved and "appointment_id" in resolved:
            break
        record = await known_patient(client, raw)
        if record is None:
            continue
        if "patient_id" not in resolved:
            resolved["patient_id"] = record.patient_id
            resolved["phone"] = record.phone or raw.get("phone", "")
            if record.insurer:
                resolved["policy_id"] = record.insurer
        if "appointment_id" in resolved:
            continue
        try:
            appointments = await client.appointments(record.patient_id, when="upcoming")
        except Exception:
            continue
        if appointments:
            resolved["appointment_id"] = appointments[0].appointment_id
            resolved["appointment_patient_id"] = record.patient_id
            if record.insurer:
                resolved["appointment_policy_id"] = record.insurer
    return resolved


def apply_resolved_inputs(recipes: dict[str, dict], resolved: dict) -> dict[str, str]:
    """Fill every recipe from ``resolved``; name the ones that stay unfillable."""
    skipped: dict[str, str] = {}
    for name, arguments in RESOLVED_INPUTS.items():
        missing = sorted({key for key in arguments.values() if resolved.get(key) is None})
        if missing:
            skipped[name] = f"no live-compatible {', '.join(missing)}"
            continue
        for argument, key in arguments.items():
            recipes[name][argument] = resolved[key]
    return skipped


async def run_scenario(
    label: str,
    base_url: str,
    api_key: str,
    *,
    share_client: bool,
    in_memory: bool,
    runs: int,
    state: PlatformState | None,
    out: dict,
) -> None:
    """Time every tool under one caching strategy."""
    shared = None
    if in_memory:
        shared = FakeClinicClient()
    elif share_client:
        shared = ClinicClient(base_url, api_key)

    warm_client = shared if shared is not None else ClinicClient(base_url, api_key)
    try:
        resolved = await resolve_inputs(warm_client)
    finally:
        if warm_client is not shared:
            await warm_client.aclose()
    recipes = tool_recipes()
    skipped = apply_resolved_inputs(recipes, resolved)

    from_number = resolved.get("phone", "")
    with tempfile.TemporaryDirectory() as tmp:
        log_dir = Path(tmp)
        for name, args in recipes.items():
            if name in skipped:
                out["scenarios"][label]["tools"][name] = {"skipped": skipped[name]}
                continue
            spec = TOOLS[name]
            samples: list[float] = []
            reqs_before = sum(state.requests.values()) if state else 0
            routes_before = Counter(state.requests) if state else Counter()
            for i in range(runs):
                if in_memory:
                    client = shared
                elif share_client:
                    client = shared
                else:
                    client = ClinicClient(base_url, api_key)
                ctx = make_context(
                    call_id=f"bench-{label}-{name}-{i}",
                    log_dir=log_dir,
                    clinic=client,
                    from_number=from_number,
                    now=datetime.now(tz=MADRID).isoformat(),
                )
                started = time.perf_counter()
                try:
                    await spec.fn(ctx, spec.input_model.model_validate(args))
                except Exception as exc:  # a broken recipe must not kill the study
                    samples = []
                    out["scenarios"][label]["tools"][name] = {
                        "error": f"{type(exc).__name__}: {exc}"
                    }
                    break
                samples.append((time.perf_counter() - started) * 1000)
                if not share_client and not in_memory:
                    await client.aclose()
            else:
                reqs_after = sum(state.requests.values()) if state else 0
                row = pct(samples)
                row["api_requests_per_call"] = (
                    round((reqs_after - reqs_before) / runs, 2) if state else None
                )
                if state:
                    delta = state.requests - routes_before
                    row["routes_per_call"] = {
                        route: round(count / runs, 2) for route, count in sorted(delta.items())
                    }
                out["scenarios"][label]["tools"][name] = row
    if shared is not None and hasattr(shared, "aclose"):
        await shared.aclose()


# ---------------------------------------------------------------------------
# Network floor: what any non-cached call pays before a byte of data moves.
# ---------------------------------------------------------------------------


def network_floor(runs: int) -> dict:
    floor: dict = {}
    try:
        # Keep-alive connection reuse: TLS+TCP paid once, then per-request cost.
        with httpx.Client(base_url=PROD_BASE_URL, timeout=10.0) as client:
            warm: list[float] = []
            for _ in range(runs):
                started = time.perf_counter()
                client.get("/api/v1/health")
                warm.append((time.perf_counter() - started) * 1000)
        floor["health_keepalive"] = pct(warm)
    except Exception as exc:
        floor["health_keepalive"] = {"error": str(exc)}
    try:
        cold: list[float] = []
        for _ in range(max(5, runs // 2)):
            with httpx.Client(base_url=PROD_BASE_URL, timeout=10.0) as client:
                started = time.perf_counter()
                client.get("/api/v1/health")
                cold.append((time.perf_counter() - started) * 1000)
        floor["health_fresh_connection"] = pct(cold)
    except Exception as exc:
        floor["health_fresh_connection"] = {"error": str(exc)}
    try:
        rejected: list[float] = []
        with httpx.Client(base_url=PROD_BASE_URL, timeout=10.0) as client:
            for _ in range(max(5, runs // 2)):
                started = time.perf_counter()
                response = client.get("/api/v1/clinic")
                rejected.append((time.perf_counter() - started) * 1000)
            floor["clinic_unauthenticated_status"] = response.status_code
        floor["clinic_unauthenticated_floor"] = pct(rejected)
    except Exception as exc:
        floor["clinic_unauthenticated_floor"] = {"error": str(exc)}
    return floor


# ---------------------------------------------------------------------------
# Cache build: what it costs to pull the whole clinic once.
# ---------------------------------------------------------------------------


async def cache_build(base_url: str, api_key: str, state: PlatformState | None) -> dict:
    client = ClinicClient(base_url, api_key)
    started = time.perf_counter()
    bytes_before = state.bytes_out if state else 0
    reqs_before = sum(state.requests.values()) if state else 0

    catalogue = await client.catalogue()
    spans: list[tuple[date, date]] = []
    day = catalogue.bookable_from
    while day <= catalogue.bookable_to:
        end = min(day + timedelta(days=catalogue.max_span_days - 1), catalogue.bookable_to)
        spans.append((day, end))
        day = end + timedelta(days=1)
    specialty_ids = [s.specialty_id for s in catalogue.specialties]
    slot_count = 0
    for specialty_id in specialty_ids:
        for span_from, span_to in spans:
            response = await client.availability(
                date_from=span_from, date_to=span_to, specialty_id=specialty_id
            )
            slot_count += len(response.slots)
    patient_ids: list[str] = []
    for raw in fixtures.PATIENTS:
        try:
            for match in await client.directory(
                phone=raw.get("phone"), national_id=raw.get("national_id")
            ):
                patient_ids.append(match.patient_id)
        except Exception:
            continue  # a fixture row without a usable exact field
    appointment_count = 0
    for patient_id in patient_ids:
        appointment_count += len(await client.appointments(patient_id, when="all"))

    elapsed = time.perf_counter() - started
    await client.aclose()
    return {
        "wall_time_s": round(elapsed, 3),
        "requests": (sum(state.requests.values()) - reqs_before) if state else None,
        "response_bytes": (state.bytes_out - bytes_before) if state else None,
        "spans": len(spans),
        "specialties": len(specialty_ids),
        "slots_pulled": slot_count,
        "patients_pulled": len(patient_ids),
        "appointments_pulled": appointment_count,
        "calendar": [str(catalogue.bookable_from), str(catalogue.bookable_to)],
    }


# ---------------------------------------------------------------------------
# Storage bake-off: where a snapshot can live, and what each choice costs.
# ---------------------------------------------------------------------------

SYNTHETIC_PATIENTS = 3000  # the clinic docs say "close to 3,000 patients"


def _synthetic_directory(n: int) -> list[dict]:
    rows = []
    for i in range(n):
        base = dict(fixtures.PATIENTS[i % len(fixtures.PATIENTS)])
        base["patient_id"] = f"P{i + 1:05d}"
        base["phone"] = f"6{i:08d}"[-9:]
        rows.append(base)
    return rows


def storage_bakeoff(full_pull_slots: list[dict], runs: int) -> dict:
    """JSON file vs SQLite vs in-memory dict, at fixture scale and at the
    documented ~3,000-patient scale (synthetic rows, real bytes and queries)."""
    import sqlite3

    patients = _synthetic_directory(SYNTHETIC_PATIENTS)
    appointments = [
        dict(
            fixtures.APPOINTMENTS[i % len(fixtures.APPOINTMENTS)],
            appointment_id=f"A{i:05d}",
            patient_id=f"P{(i % SYNTHETIC_PATIENTS) + 1:05d}",
        )
        for i in range(SYNTHETIC_PATIENTS * 2)
    ]
    slots = full_pull_slots
    report: dict = {
        "synthetic_scale": {
            "patients": len(patients),
            "appointments": len(appointments),
            "slots": len(slots),
        }
    }

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # --- JSON snapshot -------------------------------------------------
        started = time.perf_counter()
        json_path = tmp_path / "snapshot.json"
        json_path.write_text(
            json.dumps({"patients": patients, "appointments": appointments, "slots": slots})
        )
        json_build = time.perf_counter() - started
        started = time.perf_counter()
        loaded = json.loads(json_path.read_text())
        json_load = time.perf_counter() - started
        started = time.perf_counter()
        for _ in range(runs):
            [p for p in loaded["patients"] if p["phone"] == patients[1234]["phone"]]
        json_scan = (time.perf_counter() - started) / runs * 1000
        report["json"] = {
            "build_s": round(json_build, 4),
            "load_s": round(json_load, 4),
            "size_mb": round(json_path.stat().st_size / 1e6, 3),
            "patient_by_phone_scan_ms": round(json_scan, 3),
            "note": (
                "a query is a full scan unless the whole file is re-indexed in memory after load"
            ),
        }

        # --- SQLite ---------------------------------------------------------
        started = time.perf_counter()
        db_path = tmp_path / "snapshot.db"
        db = sqlite3.connect(db_path)
        db.execute("CREATE TABLE patients (patient_id TEXT PRIMARY KEY, phone TEXT, payload TEXT)")
        db.execute("CREATE INDEX idx_patients_phone ON patients(phone)")
        db.execute(
            "CREATE TABLE appointments ("
            "appointment_id TEXT PRIMARY KEY, patient_id TEXT, payload TEXT)"
        )
        db.execute("CREATE INDEX idx_appt_patient ON appointments(patient_id)")
        db.execute("CREATE TABLE slots (provider_id TEXT, day TEXT, payload TEXT)")
        db.execute("CREATE INDEX idx_slots_day ON slots(day)")
        db.executemany(
            "INSERT INTO patients VALUES (?,?,?)",
            [(p["patient_id"], p["phone"], json.dumps(p)) for p in patients],
        )
        db.executemany(
            "INSERT INTO appointments VALUES (?,?,?)",
            [(a["appointment_id"], a["patient_id"], json.dumps(a)) for a in appointments],
        )
        db.executemany(
            "INSERT INTO slots VALUES (?,?,?)",
            [(s["provider_id"], s["start_time"][:10], json.dumps(s)) for s in slots],
        )
        db.commit()
        sqlite_build = time.perf_counter() - started
        started = time.perf_counter()
        for _ in range(runs):
            db.execute(
                "SELECT payload FROM patients WHERE phone = ?", (patients[1234]["phone"],)
            ).fetchall()
        sqlite_query = (time.perf_counter() - started) / runs * 1e6
        started = time.perf_counter()
        for _ in range(runs):
            db.execute(
                "SELECT payload FROM slots WHERE day = ?",
                (slots[len(slots) // 2]["start_time"][:10],),
            ).fetchall()
        sqlite_day = (time.perf_counter() - started) / runs * 1e6
        db.close()
        report["sqlite"] = {
            "build_s": round(sqlite_build, 4),
            "size_mb": round(db_path.stat().st_size / 1e6, 3),
            "patient_by_phone_us": round(sqlite_query, 1),
            "slots_by_day_us": round(sqlite_day, 1),
        }

        # --- in-memory dicts -------------------------------------------------
        started = time.perf_counter()
        by_phone = {p["phone"]: p for p in patients}
        by_patient: dict[str, list] = {}
        for a in appointments:
            by_patient.setdefault(a["patient_id"], []).append(a)
        by_day: dict[str, list] = {}
        for s in slots:
            by_day.setdefault(s["start_time"][:10], []).append(s)
        mem_build = time.perf_counter() - started
        started = time.perf_counter()
        for _ in range(runs):
            by_phone[patients[1234]["phone"]]
        mem_query = (time.perf_counter() - started) / runs * 1e6
        payload_bytes = len(
            json.dumps({"patients": patients, "appointments": appointments, "slots": slots})
        )
        report["memory"] = {
            "build_s": round(mem_build, 4),
            "payload_mb_serialized": round(payload_bytes / 1e6, 3),
            "patient_by_phone_us": round(mem_query, 2),
            "note": (
                "payload_mb_serialized is the JSON floor; live Python objects sit ~2-4x above it"
            ),
        }
    return report


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def amain() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--runs", type=int, default=25, help="timed repetitions per tool per scenario"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="also run no_cache/current against the production API (needs PLATFORM_API_KEY)",
    )
    parser.add_argument(
        "--no-network", action="store_true", help="skip the WAN network-floor measurement"
    )
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("results.json"))
    args = parser.parse_args()

    import os

    out: dict = {
        "generated_at": datetime.now(tz=MADRID).isoformat(),
        "runs_per_tool": args.runs,
        "live": args.live,
        "scenarios": {},
    }

    server, state, base_url = start_server()
    try:
        # -- network floor ---------------------------------------------------
        if not args.no_network:
            out["network_floor"] = network_floor(args.runs)

        # -- tool scenarios over the local platform server -------------------
        out["scenarios"]["no_cache"] = {
            "tools": {},
            "meaning": "fresh HTTP client per call, nothing reused",
        }
        await run_scenario(
            "no_cache",
            base_url,
            "bench",
            share_client=False,
            in_memory=False,
            runs=args.runs,
            state=state,
            out=out,
        )
        out["scenarios"]["current"] = {
            "tools": {},
            "meaning": "shared client; only the catalogue is cached (production today)",
        }
        await run_scenario(
            "current",
            base_url,
            "bench",
            share_client=True,
            in_memory=False,
            runs=args.runs,
            state=state,
            out=out,
        )
        out["scenarios"]["full_memory"] = {
            "tools": {},
            "meaning": "everything in local memory (warm snapshot cache)",
        }
        await run_scenario(
            "full_memory",
            base_url,
            "bench",
            share_client=True,
            in_memory=True,
            runs=args.runs,
            state=state,
            out=out,
        )

        # -- live scenarios (optional) ---------------------------------------
        api_key = os.environ.get("PLATFORM_API_KEY", "")
        live_url = os.environ.get("PLATFORM_API_BASE_URL", PROD_BASE_URL)
        if args.live and api_key:
            out["scenarios"]["live_no_cache"] = {
                "tools": {},
                "meaning": "production API, nothing cached",
            }
            await run_scenario(
                "live_no_cache",
                live_url,
                api_key,
                share_client=False,
                in_memory=False,
                runs=args.runs,
                state=None,
                out=out,
            )
            out["scenarios"]["live_current"] = {
                "tools": {},
                "meaning": "production API, catalogue cached",
            }
            await run_scenario(
                "live_current",
                live_url,
                api_key,
                share_client=True,
                in_memory=False,
                runs=args.runs,
                state=None,
                out=out,
            )
            out["cache_build_live"] = await cache_build(live_url, api_key, None)
        elif args.live:
            print("!! --live needs PLATFORM_API_KEY; skipping live scenarios", file=sys.stderr)

        # -- cache build (local server) ---------------------------------------
        out["cache_build_local"] = await cache_build(base_url, "bench", state)

        # -- storage bake-off ---------------------------------------------------
        # Real slot rows for the storage test: one full-calendar pull per specialty.
        fake = FakeClinicClient()
        catalogue = Catalogue.model_validate(_adapt_catalogue(fixtures.CLINIC))
        all_slots: list[dict] = []
        day = catalogue.bookable_from
        spans = []
        while day <= catalogue.bookable_to:
            end = min(day + timedelta(days=catalogue.max_span_days - 1), catalogue.bookable_to)
            spans.append((day, end))
            day = end + timedelta(days=1)
        for specialty in catalogue.specialties:
            for span_from, span_to in spans:
                response = await fake.availability(
                    date_from=span_from, date_to=span_to, specialty_id=specialty.specialty_id
                )
                all_slots.extend(raw_slot(s) for s in response.slots)
        out["storage"] = storage_bakeoff(all_slots, args.runs)
    finally:
        server.shutdown()

    args.out.write_text(json.dumps(out, indent=2))
    print(f"results written to {args.out}")
    for label, scenario in out["scenarios"].items():
        print(f"\n### {label} — {scenario['meaning']}")
        print("| tool | p50 ms | p95 ms | api calls/req |")
        print("|---|---|---|---|")
        for name, row in scenario["tools"].items():
            if "error" in row:
                print(f"| {name} | ERROR {row['error'][:60]} | | |")
            elif "skipped" in row:
                print(f"| {name} | SKIPPED {row['skipped']} | | |")
            else:
                reqs = row.get("api_requests_per_call")
                print(f"| {name} | {row['p50_ms']} | {row['p95_ms']} | {reqs} |")
    print("\ncache_build_local:", json.dumps(out["cache_build_local"]))
    print("storage:", json.dumps(out["storage"], indent=2)[:1500])
    if "network_floor" in out:
        print("network_floor:", json.dumps(out["network_floor"]))


if __name__ == "__main__":
    asyncio.run(amain())
