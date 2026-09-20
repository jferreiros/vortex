"""The receptionist personas: the store, the line's routes, the board's proxy.

No key, no network — ``fake_store`` stands in for PostgREST and the routes
run in a TestClient.

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


@pytest.fixture
def client(offline_settings, fake_store) -> TestClient:
    return TestClient(create_app(offline_settings))


# --- the store ---------------------------------------------------------------


def test_an_empty_table_seeds_three_and_puts_one_on_the_phone(offline_settings, fake_store) -> None:
    people = personalities.list_all(offline_settings)
    assert [p.slug for p in people] == ["lucia", "mateo", "carla"]
    assert [p.active for p in people].count(True) == 1
    assert personalities.active(offline_settings).slug == "lucia"
    assert fake_store.count("personalities") == 3


def test_with_no_store_the_seeds_still_answer(offline_settings, fake_store) -> None:
    """A clinic never boots without a receptionist, keys or no keys."""
    assert [p.slug for p in personalities.list_all(offline_settings)] == [
        "lucia",
        "mateo",
        "carla",
    ]
    assert personalities.active(offline_settings).slug == "lucia"


def test_writing_without_a_store_raises_for_the_503(offline_settings) -> None:
    with pytest.raises(RuntimeError, match="no store configured"):
        personalities.activate(offline_settings, "mateo")


def test_a_second_read_does_not_reseed(offline_settings, fake_store) -> None:
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


def test_activate_moves_the_flag_and_refuses_a_stranger(offline_settings, fake_store) -> None:
    chosen = personalities.activate(offline_settings, "carla")
    assert chosen.active
    assert [p.slug for p in personalities.list_all(offline_settings) if p.active] == ["carla"]

    with pytest.raises(KeyError):
        personalities.activate(offline_settings, "nope")
    # The failed pick left the previous choice alone.
    assert personalities.active(offline_settings).slug == "carla"


def test_update_round_trips_the_json_columns_and_bumps_updated_at(
    offline_settings, fake_store
) -> None:
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


def test_update_refuses_a_stranger(offline_settings, fake_store) -> None:
    with pytest.raises(KeyError):
        personalities.update(offline_settings, "nope", {"name": "Nadie"})


def test_a_tone_longer_than_the_prompt_budget_is_rejected(offline_settings, fake_store) -> None:
    with pytest.raises(ValidationError) as error:
        personalities.update(offline_settings, "lucia", {"tone": "x" * (TONE_MAX_CHARS + 1)})
    assert str(TONE_MAX_CHARS) in str(error.value)
    # Nothing was written.
    assert personalities.get(offline_settings, "lucia").tone.startswith("Warm")


def test_an_avatar_that_can_climb_out_of_the_folder_is_rejected(
    offline_settings, fake_store
) -> None:
    for bad in ("../wall/media/avatar2d.png", "sub/dir.svg", "..", ".hidden.svg"):
        with pytest.raises(ValidationError):
            personalities.update(offline_settings, "lucia", {"avatar": bad})


def test_an_unknown_language_is_a_typo_not_a_language(offline_settings, fake_store) -> None:
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
    assert {row["id"] for row in body["styles"]} == {"warm", "brisk", "calm"}
    assert "headset" in body["looks"]


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


def test_create_from_the_simple_form(offline_settings, fake_store) -> None:
    person = personalities.create(
        offline_settings, {"name": "Nora", "style": "calm", "look": "halo"}
    )
    assert person.slug == "nora"
    assert person.avatar == "halo.svg"
    assert person.tone.startswith("Calm")
    assert personalities.get(offline_settings, "nora").name == "Nora"


def test_create_avoids_a_taken_slug(offline_settings, fake_store) -> None:
    extra = personalities.create(offline_settings, {"name": "Lucía"})
    assert extra.slug == "lucia-2"


def test_post_creates_a_persona(client: TestClient) -> None:
    r = client.post("/personalities", json={"name": "Nora", "look": "sunglasses"})
    assert r.status_code == 201
    assert r.json()["slug"] == "nora"
    assert r.json()["avatar"] == "sunglasses.svg"
    assert client.post("/personalities", json={"name": ""}).status_code == 422


# --- the board's own handlers and the art route -------------------------------
# The board reads and writes ``public.personalities`` itself — no hop to the
# line — so ``fake_store`` is the whole backend here, exactly as it is for the
# line's routes above. The NiceGUI ``user`` fixture runs the board app.


async def test_the_board_serves_the_table_rows(user: User, fake_store) -> None:
    """The rail is whatever the table holds, including an edit made a moment
    ago. Nothing is flagged offline: a board that is up can always answer,
    because it owns the same rows the line does."""
    personalities.update(None, "carla", {"name": "Carla V."})
    personalities.activate(None, "mateo")

    resp = await user.http_client.get("/api/wall/personalities")
    assert resp.status_code == 200
    body = resp.json()
    assert "offline" not in body
    assert [p["slug"] for p in body["items"]] == ["lucia", "mateo", "carla"]
    assert body["items"][2]["name"] == "Carla V."
    assert body["active"] == "mateo"
    assert {row["id"] for row in body["styles"]} == {"warm", "brisk", "calm"}
    assert "headset" in body["looks"]


async def test_the_board_writes_land_in_the_table(user: User, fake_store) -> None:
    resp = await user.http_client.post(
        "/api/wall/personalities", json={"name": "Nora", "style": "calm", "look": "halo"}
    )
    assert resp.status_code == 201
    assert resp.json()["slug"] == "nora"

    activated = await user.http_client.post("/api/wall/personalities/nora/activate")
    assert activated.status_code == 200
    assert personalities.active(None).slug == "nora"

    bad = await user.http_client.put("/api/wall/personalities/nora", json={"tone": ""})
    assert bad.status_code == 422
    assert (await user.http_client.get("/api/wall/personalities/nope")).status_code == 404


async def test_the_board_answers_503_with_no_store(user: User, offline_settings) -> None:
    """No store at all (``offline_settings`` blanks the keys): a save that
    cannot land must say so, never 200."""
    resp = await user.http_client.post("/api/wall/personalities/mateo/activate")
    assert resp.status_code == 503
    assert resp.json() == {"error": "store_unavailable"}


async def test_the_board_serves_a_vorty_head_and_an_accessory(user: User) -> None:
    face = await user.http_client.get("/wall/vorty-face-no-headphones")
    assert face.status_code == 200
    hat = await user.http_client.get("/wall/accessories/headset.svg")
    assert hat.status_code == 200
    assert hat.headers["content-type"].startswith("image/svg+xml")


async def test_the_art_route_refuses_a_climb_and_a_stranger(user: User) -> None:
    for path in ("/wall/personalities/../avatar2d.png", "/wall/personalities/nope.svg"):
        resp = await user.http_client.get(path)
        assert resp.status_code == 404, path
