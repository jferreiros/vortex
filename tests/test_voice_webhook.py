"""Live Twilio Voice webhooks: inbound and outbound TwiML into /ws."""

from __future__ import annotations

from starlette.testclient import TestClient

from vortex.line.server import create_app
from vortex.line.twilio import is_european_e164, public_ws_url, twiml_connect_stream
from vortex.settings import Settings


def test_is_european_e164_accepts_eu_rejects_us() -> None:
    assert is_european_e164("+34600000000")
    assert is_european_e164("+49301234567")
    assert is_european_e164("+33123456789")
    assert not is_european_e164("+18654867301")
    assert not is_european_e164("+15551234567")
    assert not is_european_e164("")


def test_public_ws_url_https_and_http() -> None:
    assert public_ws_url("https://demo.example.com/") == "wss://demo.example.com/ws"
    assert public_ws_url("http://localhost:7860", "/ws") == "ws://localhost:7860/ws"


def test_twiml_connect_stream_escapes_and_skips_empty() -> None:
    xml = twiml_connect_stream(
        'wss://host.example/ws?x="1"',
        {"call_id": "CA123", "from_number": "+34600", "blank": ""},
    )
    assert xml.startswith("<?xml")
    assert "<Connect>" in xml
    assert "<Stream url=" in xml
    assert "call_id" in xml
    assert "CA123" in xml
    assert "+34600" in xml
    assert "blank" not in xml
    assert "&quot;" in xml or '"' not in xml.split("url=")[1][:20]


def _client(offline_settings: Settings, base: str = "https://tunnel.example") -> TestClient:
    object.__setattr__(offline_settings, "public_base_url", base)
    return TestClient(create_app(offline_settings))


def test_incoming_returns_connect_stream(offline_settings: Settings) -> None:
    client = _client(offline_settings)
    response = client.post(
        "/voice/incoming",
        data={"CallSid": "CAabc", "From": "+34600000000"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    body = response.text
    assert "<Connect>" in body
    assert "wss://tunnel.example/ws" in body
    assert "CAabc" in body
    assert "+34600000000" in body


def test_outbound_returns_connect_stream(offline_settings: Settings) -> None:
    client = _client(offline_settings)
    response = client.get("/voice/outbound", params={"CallSid": "CAout", "To": "+34600000000"})
    assert response.status_code == 200
    assert "<Connect>" in response.text
    assert "wss://tunnel.example/ws" in response.text
    assert "CAout" in response.text
    assert "+34600000000" in response.text


def test_voice_routes_need_public_base(offline_settings: Settings) -> None:
    client = _client(offline_settings, base="")
    response = client.post("/voice/incoming", data={"CallSid": "CA1", "From": "+1"})
    assert response.status_code == 400
    assert "VORTEX_PUBLIC_BASE_URL" in response.text


def test_voice_status_is_empty_ok(offline_settings: Settings) -> None:
    client = _client(offline_settings)
    assert client.post("/voice/status").status_code == 204
