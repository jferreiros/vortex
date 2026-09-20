"""Shared fixtures.

Most tests run with no key and no store: the clinic is fixtures, the voice
pipeline is the stub, and ``CallLog`` writes into an in-memory list instead of
Postgres (``_stub_call_events``). Nothing reaches the network.

The exception is a test that genuinely needs a database. It asks for the
``requires_db`` fixture (or carries the ``requires_db`` marker) and skips
itself when ``SUPABASE_URL`` / ``SUPABASE_SERVICE_ROLE_KEY`` are not set,
because Postgres is the only store there is — there is no file log and no
SQLite double to stand in for it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from vortex import settings as settings_module

# NiceGUI's simulated user for the console page tests; it registers the
# `main_file` ini option, so it has to load from conftest, not a test module.
pytest_plugins = ["nicegui.testing.user_plugin"]

#: Keys that must never leak in from a developer's ``.env``.
_BLANK_KEYS = (
    "PLATFORM_API_KEY",
    "SONIOX_API_KEY",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "HELMCODE_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_DEPLOYMENT",
    "AZURE_OPENAI_API_VERSION",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_VOICE_ID_ES",
    "ELEVENLABS_VOICE_ID_DEFAULT",
    "DISCORD_WEBHOOK_URL",
    "DISCORD_CALLS_WEBHOOK_URL",
    "DISCORD_NOTIFY_IN_TESTS",
    "VORTEX_JEV_ARBITER",
    "TYPESAFE_API_KEY",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_MESSAGING_SERVICE_SID",
    "TWILIO_FROM_NUMBER",
    "VORTEX_SMS_CONFIRMATIONS",
    "HF_TOKEN",
    "VORTEX_SMS_FORCE_TO",
    "VORTEX_SMS_DAY_BEFORE",
    "VORTEX_SMS_REMINDER_LEAD_HOURS",
    "VORTEX_SMS_REMINDER_POLL_SECS",
    "VORTEX_SMS_REMINDERS_PATH",
    "VORTEX_CONFIRMATION_CALLS",
    "VORTEX_PUBLIC_BASE_URL",
    "VORTEX_CONFIRMATION_LEAD_HOURS",
    "VORTEX_CONFIRMATION_CALLS_PATH",
    "VORTEX_CONFIRMATION_POLL_SECS",
    "VORTEX_CONFIRMATION_FORCE_TO",
)

#: Deliberately *not* blanked at import: a developer with a project
#: configured should have the ``requires_db`` tests actually run. They are
#: still blanked per test by ``offline_settings``, which is what an offline
#: test wants, and ``_stub_call_events`` keeps call events out of a real
#: project either way.
_STORE_KEYS = (
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_SECRET_KEY",
    "SUPABASE_DB_URL",
)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "requires_db: needs a real Supabase project; skipped without "
        "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY",
    )


def db_configured() -> bool:
    return bool(
        os.environ.get("SUPABASE_URL", "").strip()
        and (
            os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
            or os.environ.get("SUPABASE_SECRET_KEY", "").strip()
        )
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if db_configured():
        return
    skip = pytest.mark.skip(reason="needs SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY")
    for item in items:
        if "requires_db" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def requires_db() -> None:
    """Skip unless a real Supabase project is configured.

    There is deliberately no double: a SQLite stand-in would test a store the
    product does not have, and the failures worth catching here are PostgREST
    ones — a wrong filter, a missing column, an RLS policy.
    """
    if not db_configured():
        pytest.skip("needs SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY")


#: The events the current test wrote, shared so a module-level helper can
#: reach them without threading a fixture through every call site.
_CAPTURED: list[dict[str, Any]] = []


def captured_events() -> list[dict[str, Any]]:
    """Every call event written since this test started.

    The replacement for reading ``logs/calls.jsonl`` back: there is no file,
    and a test that wants to know what a call recorded asks here (or reads
    ``CallLog.events`` when it holds the log itself).
    """
    return list(_CAPTURED)


@pytest.fixture(autouse=True)
def _stub_call_events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Catch ``CallLog`` writes in a list when there is no database.

    Offline tests still exercise the whole write path — ``event()``, the
    JSON-safety round trip, ``flush()`` — they just land here instead of in
    ``public.call_events``. With a real project configured this steps aside,
    so a ``requires_db`` test talks to Postgres for real.
    """
    _CAPTURED.clear()
    written = _CAPTURED
    if db_configured():
        return written

    from vortex.observability import supabase_log

    monkeypatch.setattr(supabase_log, "enqueue", written.append)
    monkeypatch.setattr(
        supabase_log,
        "upsert_events",
        lambda events, **_kw: (written.extend(events), len(events))[1],
    )
    monkeypatch.setattr(supabase_log, "flush", lambda *_a, **_kw: None)
    return written


class FakeTables:
    """A dictionary that answers the slice of PostgREST our modules use.

    Not a database: it understands ``select``, ``eq.`` filters, ``order`` and
    ``limit``, and nothing else. That is exactly the surface
    ``voice_config``, ``personalities`` and ``rebooking`` reach for, so their
    real logic — clamping, seeding, the one-active-persona invariant,
    idempotent queueing — stays under test with no project configured. A
    query these modules do not make is not worth faking; tests that need
    real PostgREST ask for ``requires_db`` instead.
    """

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}

    def enabled(self) -> bool:
        return True

    def _match(self, row: dict[str, Any], params: dict[str, str]) -> bool:
        for key, raw in params.items():
            if key in {"select", "order", "limit", "offset"}:
                continue
            if not str(raw).startswith("eq."):
                raise AssertionError(f"FakeTables only does eq. filters, got {key}={raw}")
            if str(row.get(key)) != str(raw)[3:]:
                return False
        return True

    def select(
        self, table: str, params: dict[str, str] | None = None
    ) -> list[dict[str, Any]] | None:
        params = params or {}
        rows = [dict(r) for r in self.tables.get(table, []) if self._match(r, params)]
        for term in reversed(str(params.get("order", "")).split(",")):
            term = term.strip()
            if not term:
                continue
            column, _, direction = term.partition(".")
            rows.sort(
                key=lambda r: (r.get(column) is None, r.get(column)),
                reverse="desc" in direction,
            )
        if params.get("limit"):
            rows = rows[: int(params["limit"])]
        return rows

    def upsert(
        self, table: str, rows: list[dict[str, Any]], on_conflict: str | None = None
    ) -> list[dict[str, Any]]:
        stored = self.tables.setdefault(table, [])
        for row in rows:
            existing = (
                next((r for r in stored if r.get(on_conflict) == row.get(on_conflict)), None)
                if on_conflict
                else None
            )
            if existing is None:
                stored.append(dict(row))
            else:
                existing.update(row)
        return [dict(r) for r in rows]

    def safe_upsert(
        self, table: str, rows: list[dict[str, Any]], on_conflict: str | None = None
    ) -> None:
        self.upsert(table, rows, on_conflict)

    def update(
        self, table: str, params: dict[str, str], values: dict[str, Any]
    ) -> list[dict[str, Any]]:
        hit = [r for r in self.tables.get(table, []) if self._match(r, params)]
        for row in hit:
            row.update(values)
        return [dict(r) for r in hit]

    def delete(self, table: str, params: dict[str, str]) -> int:
        stored = self.tables.get(table, [])
        keep = [r for r in stored if not self._match(r, params)]
        removed = len(stored) - len(keep)
        self.tables[table] = keep
        return removed

    def count(self, table: str) -> int:
        return len(self.tables.get(table, []))


@pytest.fixture
def fake_store(monkeypatch: pytest.MonkeyPatch) -> FakeTables:
    """``database.remote`` backed by ``FakeTables`` for this test."""
    from database import remote

    fake = FakeTables()
    for name in ("enabled", "select", "upsert", "safe_upsert", "update", "delete", "count"):
        monkeypatch.setattr(remote, name, getattr(fake, name))
    from vortex.line import personalities

    monkeypatch.setattr(personalities, "_seeded", False)
    return fake


@pytest.fixture(autouse=True)
def _isolate_board_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    """A local ``make run`` must not answer the board tests' fetch."""
    from vortex.observability import callfeed

    monkeypatch.setattr(callfeed, "LINE_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(callfeed, "_last_good", {})
    monkeypatch.setattr(callfeed, "_scope_cache", {})


@pytest.fixture
def offline_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> settings_module.Settings:
    """Settings with every key blank and every scratch file in a temp dir."""
    for key in (*_BLANK_KEYS, *_STORE_KEYS):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("VORTEX_VOICE_MODE", "stub")
    monkeypatch.setenv("VORTEX_CLINIC_MODE", "fake")
    # The two JSON queues and the TTS cache are local scratch, not the store.
    # Point them at the test's own tmp dir so nothing lands in repo logs/.
    monkeypatch.setenv("VORTEX_SMS_REMINDERS_PATH", str(tmp_path / "sms_reminders.json"))
    monkeypatch.setenv("VORTEX_CONFIRMATION_CALLS_PATH", str(tmp_path / "confirmation_calls.json"))
    monkeypatch.setenv("VORTEX_CONFIRMATION_AUDIO_DIR", str(tmp_path / "confirmation_audio"))
    settings_module.reset_settings()
    yield settings_module.get_settings()
    settings_module.reset_settings()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _unset_dotenv_keys() -> None:
    # A developer's .env must not leak into the tests.
    for key in _BLANK_KEYS:
        os.environ.pop(key, None)


_unset_dotenv_keys()
