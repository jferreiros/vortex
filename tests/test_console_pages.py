"""The console pages render. A template crash here is a blank wall on the day.

Uses NiceGUI's simulated user: no browser, no port, the pages run in-process.

Two halves. The first needs nothing: every console route is opened against an
empty call feed, which is the state a fresh clone (and a board whose store is
unreachable) is in — a page that crashes on "no calls yet" is exactly the
blank wall this file exists to catch. The second half seeds two scripted
calls and checks what the pages say about them, which needs a migrated
Supabase project to write into.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User

from vortex.observability.demo import write_scripted_call

HAS_DB = bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
needs_db = pytest.mark.skipif(not HAS_DB, reason="needs migrated Supabase")


@pytest.fixture
def offline_board(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A board with no line and no clinic key. Defined here rather than in
    conftest because it is only these pages that need the line silenced."""
    monkeypatch.setenv("VORTEX_VOICE_MODE", "stub")
    monkeypatch.setenv("VORTEX_CLINIC_MODE", "fake")
    from vortex import settings

    settings.reset_settings()

    def _offline_get(*_args: object, **_kwargs: object) -> object:
        raise OSError("offline")

    monkeypatch.setattr("httpx.get", _offline_get)
    yield
    settings.reset_settings()


@pytest.fixture
def seeded(offline_board: None) -> Iterator[list[str]]:
    """Two scripted calls in the store: one refusal, one booking."""
    import asyncio

    ids = [
        asyncio.run(write_scripted_call(scenario="refuse", delay_s=0)),
        asyncio.run(write_scripted_call(scenario="book", delay_s=0)),
    ]
    yield ids


# ---------------------------------------------------------------------------
# No store needed: every route renders on an empty feed
# ---------------------------------------------------------------------------


async def test_console_routes_render(offline_board: None, user: User) -> None:
    for path, text in (
        ("/", "Overview"),
        ("/agents", "Agents"),
        ("/agents/scheduling", "Tools it can call"),
        ("/agents/reminders", "Preview"),
        ("/agents/nope", "No agent with this name"),
        ("/calls", "Calls"),
        ("/calls/live", "Waiting for the next call"),
        ("/patients", "Patients"),
        ("/insights", "Insights"),
        ("/settings", "Clinic"),
        ("/settings/rules", "Rules"),
        ("/settings/integrations", "Integrations"),
        ("/settings/engineering", "Engineering"),
    ):
        await user.open(path)
        await user.should_see(text)


async def test_public_wall_renders_with_no_calls(offline_board: None, user: User) -> None:
    await user.open("/wall/classic")
    await user.should_see("Live")
    await user.open("/wall/flow")
    await user.should_see("Waiting for the next call")


async def test_unknown_call_has_an_empty_state(offline_board: None, user: User) -> None:
    await user.open("/call/nope")
    await user.should_see("No call with this id yet")


async def test_calendar_page_renders_doctor_grids(offline_board: None, user: User) -> None:
    await user.open("/calendar")
    await user.should_see("Calendar")
    await user.should_see("Type your name to open it.")
    await user.should_not_see("Dra. Ortiz")


async def test_calendar_login_opens_one_diary_and_a_visit(
    offline_board: None, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VORTEX_CALENDAR_TODAY", "2026-09-19")
    await user.open("/calendar")
    user.find(ui.input).type("Dra. Ortiz")
    user.find("Open").click()
    await user.should_see("Dra. Ortiz")
    await user.should_see("Next")
    await user.should_see("Today")
    await user.should_not_see("Dr. Sáez")
    await user.should_not_see("Roster record")
    await user.should_not_see("Fake record")


async def test_calendar_hides_patient_data_on_a_booked_slot(
    offline_board: None, user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The grid is public: a taken slot says it is taken and nothing else.

    ``VORTEX_CALENDAR_LOG`` still points at a file — it is a replay input for
    the doctor grid, not the product's call store.
    """
    calendar_log = tmp_path / "calendar.jsonl"
    booking = {
        "kind": "submit.result",
        "call_id": "cal-privacy",
        "ts": "2026-09-07T10:00:00+02:00",
        "payload": {
            "action": "BOOK",
            "patient_id": "P-LEAKED-ID",
            "provider_id": "PR01",
            "location_id": "centro",
            "appointment_type_id": "T-LEAKED-TYPE",
            "slot": "2026-09-08T10:00:00+02:00",
        },
    }
    calendar_log.write_text(json.dumps(booking) + "\n", encoding="utf-8")
    monkeypatch.setenv("VORTEX_CALENDAR_LOG", str(calendar_log))

    await user.open("/calendar")
    # The pill proves the booking reached the grid, so the checks below are real.
    await user.should_see("1 booked")
    await user.should_not_see("P-LEAKED-ID")
    await user.should_not_see("T-LEAKED-TYPE")


async def test_the_wall_reads_its_cards_off_the_event_loop(
    offline_board: None, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A redraw runs on the event loop twice a second. The reads behind it
    must not, or a store that does not answer freezes every open tab."""
    threads: list[int] = []

    def _offline_get(*_args: object, **_kwargs: object) -> object:
        threads.append(threading.get_ident())
        raise OSError("offline")

    monkeypatch.setattr("httpx.get", _offline_get)
    await user.open("/wall/classic")
    assert threads
    assert threading.get_ident() not in threads


async def test_unsigned_root_is_sign_in_not_the_wall(
    offline_board: None, monkeypatch: pytest.MonkeyPatch, user: User
) -> None:
    monkeypatch.setenv("VORTEX_OPS_PASSWORD", "secret")
    monkeypatch.setenv("VORTEX_ENV", "production")
    monkeypatch.setenv("VORTEX_STORAGE_SECRET", "test-secret")
    await user.open("/")
    await user.should_see("Team sign-in")
    await user.should_not_see("Recent calls")
    await user.should_not_see("Overview")


# ---------------------------------------------------------------------------
# What the pages say about real calls — needs the store to seed them
# ---------------------------------------------------------------------------


@needs_db
async def test_wall_shows_the_last_call_and_why(seeded: list[str], user: User) -> None:
    await user.open("/wall/classic")
    await user.should_see("Live")
    await user.should_see("Booked")
    await user.should_see("Marta Ruiz López")
    await user.should_see("Recent calls")
    await user.should_see("insurance does not cover")


@needs_db
async def test_call_page_explains_a_refusal(
    seeded: list[str], user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VORTEX_OPS_PASSWORD", raising=False)
    monkeypatch.delenv("VORTEX_ENV", raising=False)
    refused = next(i for i in seeded if i.startswith("demo-refuse"))
    await user.open(f"/call/{refused}")
    await user.should_see("No action")
    await user.should_see("insurance does not cover")
    await user.should_see("Check the clinic's rules and the insurance matrix")
    await user.should_not_see("Timeline")
    await user.should_not_see("Request and response")
    await user.should_not_see("+34612345678")


@needs_db
async def test_signed_in_call_page_shows_the_team_view(
    seeded: list[str], user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VORTEX_OPS_PASSWORD", "team-secret")
    monkeypatch.delenv("VORTEX_ENV", raising=False)
    refused = next(i for i in seeded if i.startswith("demo-refuse"))
    await user.open("/calls")
    user.find(ui.input).type("team-secret")
    user.find("Sign in").click()
    await user.open(f"/call/{refused}")
    await user.should_see("Timeline")
    await user.should_see("The socket closed.")
    await user.should_see("GET /api/v1/availability + GET /api/v1/clinic")
    await user.should_see("Request and response")
    await user.should_see("+34612345678")


@needs_db
async def test_calls_page_lists_and_filters(seeded: list[str], user: User) -> None:
    await user.open("/")
    await user.should_see("Calls")
    await user.should_see("Why not booked")
    await user.should_see("Andrés Ruiz")


@needs_db
async def test_public_pages_mask_the_phone(seeded: list[str], user: User) -> None:
    await user.open("/wall/classic")
    await user.should_not_see("+34612345678")


@needs_db
async def test_insights_shows_what_a_call_costs(seeded: list[str], user: User) -> None:
    await user.open("/insights")
    await user.should_see("€/call (list)")
    await user.should_see("€/call (we pay)")
    await user.should_see("€ today (list)")
    await user.should_see("p95 handle time")
    # The seeded refusal ends on a Gemini voice with no published price, so the
    # page has to say which leg it left out rather than quietly averaging it in.
    await user.should_see("gemini-2.5-flash-tts")


@needs_db
async def test_call_page_shows_the_cost_of_that_call(seeded: list[str], user: User) -> None:
    booked = next(i for i in seeded if i.startswith("demo-book"))
    await user.open(f"/call/{booked}")
    await user.should_see("Cost (list)")
    await user.should_see("Cost (we pay)")
    await user.should_see("perk")
