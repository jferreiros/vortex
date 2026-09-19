"""The console pages render. A template crash here is a blank wall on the day.

Uses NiceGUI's simulated user: no browser, no port, the pages run in-process
against a seeded call log.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User

from vortex.observability.demo import write_scripted_call


@pytest.fixture
def seeded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    log = tmp_path / "calls.jsonl"
    asyncio.run(write_scripted_call(log, scenario="refuse", delay_s=0))
    asyncio.run(write_scripted_call(log, scenario="book", delay_s=0))
    monkeypatch.setenv("VORTEX_CALLS_LOG", str(log))
    from vortex import settings

    settings.reset_settings()

    def _offline_get(*_args: object, **_kwargs: object) -> object:
        raise OSError("offline")

    monkeypatch.setattr("httpx.get", _offline_get)
    yield log
    settings.reset_settings()


async def test_wall_shows_the_last_call_and_why(seeded: Path, user: User) -> None:
    await user.open("/wall/classic")
    await user.should_see("Live")
    await user.should_see("Booked")
    await user.should_see("Marta Ruiz López")
    await user.should_see("Recent calls")
    await user.should_see("insurance does not cover")


def test_the_seeded_log_does_not_outlive_the_fixture(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """The regression: the wall above cached its temp log path past teardown.

    Reads the settings the previous test left behind, so it has to stay right
    after a page test that resolves the call log.
    """
    from vortex import settings

    cached_log = settings.get_settings().calls_log_path
    assert tmp_path_factory.getbasetemp() not in cached_log.parents


async def test_call_page_explains_a_refusal(
    seeded: Path, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VORTEX_OPS_PASSWORD", raising=False)
    monkeypatch.delenv("VORTEX_ENV", raising=False)
    ids = [line.split('"call_id": "')[1].split('"')[0] for line in seeded.read_text().splitlines()]
    refused = next(i for i in ids if i.startswith("demo-refuse"))
    await user.open(f"/call/{refused}")
    await user.should_see("No action")
    await user.should_see("insurance does not cover")
    await user.should_see("Check the clinic's rules and the insurance matrix")
    await user.should_not_see("Timeline")
    await user.should_not_see("Request and response")
    await user.should_not_see("+34612345678")


async def test_signed_in_call_page_shows_the_team_view(
    seeded: Path, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VORTEX_OPS_PASSWORD", "team-secret")
    monkeypatch.delenv("VORTEX_ENV", raising=False)
    ids = [line.split('"call_id": "')[1].split('"')[0] for line in seeded.read_text().splitlines()]
    refused = next(i for i in ids if i.startswith("demo-refuse"))
    await user.open("/calls")
    user.find(ui.input).type("team-secret")
    user.find("Sign in").click()
    await user.open(f"/call/{refused}")
    await user.should_see("Timeline")
    await user.should_see("The socket closed.")
    await user.should_see("GET /api/v1/availability + GET /api/v1/clinic")
    await user.should_see("Request and response")
    await user.should_see("+34612345678")


async def test_unknown_call_has_an_empty_state(seeded: Path, user: User) -> None:
    await user.open("/call/nope")
    await user.should_see("No call with this id yet")


async def test_calls_page_lists_and_filters(seeded: Path, user: User) -> None:
    await user.open("/")
    await user.should_see("Calls")
    await user.should_see("Why not booked")
    await user.should_see("Andrés Ruiz")


async def test_console_routes_render(seeded: Path, user: User) -> None:
    for path, text in (
        ("/", "Overview"),
        ("/agents", "Scheduling"),
        ("/agents/scheduling", "Tools it can call"),
        ("/agents/reminders", "Preview"),
        ("/agents/nope", "No agent with this name"),
        ("/calls", "Why not booked"),
        ("/calls/live", "Call opened"),
        ("/patients", "Marta Ruiz López"),
        ("/insights", "Why not booked"),
        ("/settings", "Sites"),
        ("/settings/rules", "Refusal reasons"),
        ("/settings/integrations", "Telephony"),
        ("/settings/engineering", "Evals"),
    ):
        await user.open(path)
        await user.should_see(text)


async def test_calendar_page_renders_doctor_grids(seeded: Path, user: User) -> None:
    await user.open("/calendar")
    await user.should_see("Calendar")
    await user.should_see("Type your name to open it.")
    await user.should_not_see("Dra. Ortiz")


async def test_calendar_login_opens_one_diary_and_a_visit(
    seeded: Path, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VORTEX_CALENDAR_TODAY", "2026-09-19")
    await user.open("/calendar")
    user.find(ui.input).type("Dra. Ortiz")
    user.find("Open").click()
    await user.should_see("Dra. Ortiz")
    await user.should_see("Next")
    await user.should_see("Today")
    await user.should_not_see("Dr. Sáez")
    await user.should_see("Teresa López García")
    await user.should_not_see("Roster record")
    await user.should_not_see("Fake record")


async def test_calendar_hides_patient_data_on_a_booked_slot(
    seeded: Path, user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The grid is public: a taken slot says it is taken and nothing else."""
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


async def test_public_pages_mask_the_phone(seeded: Path, user: User) -> None:
    await user.open("/wall/classic")
    await user.should_not_see("+34612345678")


async def test_the_wall_reads_its_cards_off_the_event_loop(
    seeded: Path, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A redraw runs on the event loop twice a second. The HTTP calls behind it
    must not, or a line that does not answer freezes every open tab."""
    threads: list[int] = []

    def _offline_get(*_args: object, **_kwargs: object) -> object:
        threads.append(threading.get_ident())
        raise OSError("offline")

    monkeypatch.setattr("httpx.get", _offline_get)
    await user.open("/wall/classic")
    assert threads
    assert threading.get_ident() not in threads


async def test_a_second_tab_reuses_the_first_load(
    seeded: Path, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One load for the whole board: three tabs on the wall are not three loads."""
    calls: list[object] = []

    def _offline_get(url: object = "", *_args: object, **_kwargs: object) -> object:
        calls.append(url)
        raise OSError("offline")

    monkeypatch.setattr("httpx.get", _offline_get)
    await user.open("/wall/classic")
    first = len(calls)
    assert first
    await user.open("/wall/classic")
    assert len(calls) == first


async def test_unsigned_root_is_sign_in_not_the_wall(
    seeded: Path, monkeypatch: pytest.MonkeyPatch, user: User
) -> None:
    monkeypatch.setenv("VORTEX_OPS_PASSWORD", "secret")
    monkeypatch.setenv("VORTEX_ENV", "production")
    monkeypatch.setenv("VORTEX_STORAGE_SECRET", "test-secret")
    await user.open("/")
    await user.should_see("Team sign-in")
    await user.should_not_see("Recent calls")
    await user.should_not_see("Overview")


# New tests go below this line: the guard above reads the settings the wall
# test leaves behind, so nothing may be inserted between the two.


async def test_insights_shows_what_a_call_costs(seeded: Path, user: User) -> None:
    await user.open("/insights")
    await user.should_see("€/call (list)")
    await user.should_see("€/call (we pay)")
    await user.should_see("€ today (list)")
    await user.should_see("p95 handle time")
    # The seeded refusal ends on a Gemini voice with no published price, so the
    # page has to say which leg it left out rather than quietly averaging it in.
    await user.should_see("1 of 2 calls priced")
    await user.should_see("gemini-2.5-flash-tts")


async def test_call_page_shows_the_cost_of_that_call(seeded: Path, user: User) -> None:
    ids = [line.split('"call_id": "')[1].split('"')[0] for line in seeded.read_text().splitlines()]
    booked = next(i for i in ids if i.startswith("demo-book"))
    await user.open(f"/call/{booked}")
    await user.should_see("Cost (list)")
    await user.should_see("Cost (we pay)")
    await user.should_see("perk")
