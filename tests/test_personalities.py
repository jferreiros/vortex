"""The receptionist personas: the store, the line's routes, the board's proxy.

No key, no network — the db is a sqlite file next to the test call log and the
routes run in a TestClient.

The invariant the picker leans on is "exactly one persona is active". Most of
what follows is about keeping that true across a seed, a reopen and a pick.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from nicegui.testing import User
from pydantic import ValidationError

from vortex.line import personalities
from vortex.line.personalities import TONE_MAX_CHARS
from vortex.line.server import create_app
from vortex.observability import callfeed


@pytest.fixture
def client(offline_settings) -> TestClient:
    return TestClient(create_app(offline_settings))


# --- the store ---------------------------------------------------------------


def test_a_fresh_file_seeds_three_and_puts_one_on_the_phone(offline_settings) -> None:
    people = personalities.list_all(offline_settings)
    assert [p.slug for p in people] == ["lucia", "mateo", "carla"]
    assert [p.active for p in people].count(True) == 1
    assert personalities.active(offline_settings).slug == "lucia"
    assert personalities.db_path(offline_settings).name == "personalities.db"
    assert personalities.db_path(offline_settings).parent == offline_settings.calls_log_path.parent


def test_reopening_the_same_file_does_not_reseed(offline_settings) -> None:
    personalities.update(offline_settings, "lucia", {"name": "Lucía R."})
    personalities.activate(offline_settings, "mateo")

    # Every call opens the file again; the second open must not seed over it.
    assert [p.slug for p in personalities.list_all(offline_settings)] == [
        "lucia",
        "mateo",
        "carla",
    ]
    assert personalities.get(offline_settings, "lucia").name == "Lucía R."
    assert personalities.active(offline_settings).slug == "mateo"


def test_activate_moves_the_flag_and_refuses_a_stranger(offline_settings) -> None:
    chosen = personalities.activate(offline_settings, "carla")
    assert chosen.active
    assert [p.slug for p in personalities.list_all(offline_settings) if p.active] == ["carla"]

    with pytest.raises(KeyError):
        personalities.activate(offline_settings, "nope")
    # The failed pick left the previous choice alone.
    assert personalities.active(offline_settings).slug == "carla"


def test_update_round_trips_the_json_columns_and_bumps_updated_at(offline_settings) -> None:
    before = personalities.get(offline_settings, "mateo")
    after = personalities.update(
        offline_settings,
        "mateo",
        {
            "role": "Agenda de fin de semana",
            "greetings": {
                "en": "Clínica Arenal, Mateo here.",
                "ca": "Clínica Arenal, sóc en Mateo.",
            },
            "voices": {"en": "en-GB-Chirp3-HD-Aoede", "ca": "ca-ES-Standard-A"},
        },
    )
    assert after.role == "Agenda de fin de semana"
    assert after.greetings == {
        "en": "Clínica Arenal, Mateo here.",
        "ca": "Clínica Arenal, sóc en Mateo.",
    }
    assert after.voices["ca"] == "ca-ES-Standard-A"
    assert after.updated_at > before.updated_at
    assert after.created_at == before.created_at
    # And it survives a reopen, which is the point of the *_json columns.
    reopened = personalities.get(offline_settings, "mateo")
    assert reopened.greetings == after.greetings
    assert reopened.voices == after.voices


def test_update_refuses_a_stranger(offline_settings) -> None:
    with pytest.raises(KeyError):
        personalities.update(offline_settings, "nope", {"name": "Nadie"})


def test_a_tone_longer_than_the_prompt_budget_is_rejected(offline_settings) -> None:
    with pytest.raises(ValidationError) as error:
        personalities.update(offline_settings, "lucia", {"tone": "x" * (TONE_MAX_CHARS + 1)})
    assert str(TONE_MAX_CHARS) in str(error.value)
    # Nothing was written.
    assert personalities.get(offline_settings, "lucia").tone.startswith("Warm")


def test_an_avatar_that_can_climb_out_of_the_folder_is_rejected(offline_settings) -> None:
    for bad in ("../wall/media/avatar2d.png", "sub/dir.svg", "..", ".hidden.svg"):
        with pytest.raises(ValidationError):
            personalities.update(offline_settings, "lucia", {"avatar": bad})


def test_an_unknown_language_is_a_typo_not_a_language(offline_settings) -> None:
    with pytest.raises(ValidationError):
        personalities.update(offline_settings, "lucia", {"greetings": {"fr": "Bonjour"}})


def test_defaults_mirror_the_seeds_with_the_first_one_active() -> None:
    assert [p["slug"] for p in personalities.DEFAULTS] == ["lucia", "mateo", "carla"]
    assert [p["active"] for p in personalities.DEFAULTS] == [True, False, False]


# --- the line's routes --------------------------------------------------------


def test_get_lists_the_personas_and_names_the_active_one(client: TestClient) -> None:
    body = client.get("/personalities").json()
    assert [p["slug"] for p in body["items"]] == ["lucia", "mateo", "carla"]
    assert body["active"] == "lucia"
    assert body["items"][0]["greetings"]["es"].startswith("Clínica Arenal")


def test_get_one_and_an_unknown_one(client: TestClient) -> None:
    assert client.get("/personalities/carla").json()["name"] == "Carla"
    missing = client.get("/personalities/nope")
    assert missing.status_code == 404
    assert "nope" in missing.json()["error"]


def test_put_saves_the_form(client: TestClient) -> None:
    r = client.put("/personalities/lucia", json={"name": "Lucía R.", "tone": "Be brief."})
    assert r.status_code == 200
    assert r.json()["name"] == "Lucía R."
    assert client.get("/personalities/lucia").json()["tone"] == "Be brief."


def test_put_rejects_a_tone_that_will_not_fit_the_prompt(client: TestClient) -> None:
    r = client.put("/personalities/lucia", json={"tone": "x" * (TONE_MAX_CHARS + 1)})
    assert r.status_code == 422
    assert str(TONE_MAX_CHARS) in r.json()["error"]
    assert "tone" in r.json()["error"]


def test_put_on_an_unknown_persona_is_a_404(client: TestClient) -> None:
    assert client.put("/personalities/nope", json={"name": "Nadie"}).status_code == 404


def test_activate_changes_who_answers(client: TestClient) -> None:
    r = client.post("/personalities/mateo/activate")
    assert r.status_code == 200
    assert r.json()["active"] is True
    assert client.get("/personalities").json()["active"] == "mateo"
    assert client.post("/personalities/nope/activate").status_code == 404


# --- the board's proxy and the art route --------------------------------------
# Same arrangement as tests/test_call_ingestion.py: the NiceGUI `user` fixture
# runs the board app, and patching ``httpx.get`` through callfeed (a leaf
# module holding the same httpx module object live.py uses) stands in for the
# line being up or down without importing live.py here.


async def test_the_board_falls_back_to_the_seeds_when_the_line_is_down(
    user: User, monkeypatch: pytest.MonkeyPatch, offline_settings
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise OSError("offline")

    monkeypatch.setattr(callfeed.httpx, "get", boom)
    resp = await user.http_client.get("/api/wall/personalities")
    assert resp.status_code == 200
    body = resp.json()
    assert body["offline"] is True
    assert body["active"] == "lucia"
    assert [p["slug"] for p in body["items"]] == ["lucia", "mateo", "carla"]


async def test_the_board_serves_a_persona_portrait(user: User) -> None:
    resp = await user.http_client.get("/wall/personalities/lucia.svg")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")


async def test_the_art_route_refuses_a_climb_and_a_stranger(user: User) -> None:
    for path in ("/wall/personalities/../avatar2d.png", "/wall/personalities/nope.svg"):
        resp = await user.http_client.get(path)
        assert resp.status_code == 404, path
