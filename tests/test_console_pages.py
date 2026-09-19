"""The console pages render. A template crash here is a blank wall on the day.

Uses NiceGUI's simulated user: no browser, no port, the pages run in-process
against a seeded call log.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from nicegui.testing import User

from vortex.observability.demo import write_scripted_call


@pytest.fixture
def seeded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    log = tmp_path / "calls.jsonl"
    asyncio.run(write_scripted_call(log, scenario="refuse", delay_s=0))
    asyncio.run(write_scripted_call(log, scenario="book", delay_s=0))
    monkeypatch.setenv("VORTEX_CALLS_LOG", str(log))
    from vortex import settings

    settings.reset_settings()

    def _offline_get(*_args: object, **_kwargs: object) -> object:
        raise OSError("offline")

    monkeypatch.setattr("httpx.get", _offline_get)
    return log


async def test_wall_shows_the_last_call_and_why(seeded: Path, user: User) -> None:
    await user.open("/wall")
    await user.should_see("Live")
    await user.should_see("Booked")
    await user.should_see("Marta Ruiz López")
    await user.should_see("Recent calls")
    await user.should_see("specialty_not_covered")


async def test_call_page_explains_a_refusal(seeded: Path, user: User) -> None:
    ids = [line.split('"call_id": "')[1].split('"')[0] for line in seeded.read_text().splitlines()]
    refused = next(i for i in ids if i.startswith("demo-refuse"))
    await user.open(f"/call/{refused}")
    await user.should_see("No action")
    await user.should_see("insurance does not cover")
    await user.should_see("Check the clinic's rules and the insurance matrix")
    await user.should_see("Timeline")
    await user.should_see("The socket closed.")
    await user.should_see("GET /api/v1/availability + GET /api/v1/clinic")


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
        ("/calls/live", "Transcript"),
        ("/patients", "Marta Ruiz López"),
        ("/insights", "Why not booked"),
        ("/settings", "Sites"),
        ("/settings/rules", "Refusal reasons"),
        ("/settings/integrations", "Telephony"),
        ("/settings/engineering", "Evals"),
    ):
        await user.open(path)
        await user.should_see(text)


async def test_public_pages_mask_the_phone(seeded: Path, user: User) -> None:
    await user.open("/wall")
    await user.should_not_see("+34612345678")
