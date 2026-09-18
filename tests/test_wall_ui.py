"""Serve the real public pages, including their generated NiceGUI element tree."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
import pytest

from vortex.observability.calllog import CallLog


@pytest.fixture
def board_url(tmp_path):
    pytest.importorskip("nicegui")
    log_path = tmp_path / "calls.jsonl"
    log = CallLog("demo-call & special", log_path)
    log.event("call.started", voice="demo")
    log.event("call.state", state="OFFERING")
    log = CallLog("finished-call", log_path)
    log.event("call.started", language="ca")
    log.action_submitted("/api/v1/submit/book", {}, {"status": "accepted"})
    log.event("call.ended")
    log.event("call.verdict", passed=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        **os.environ,
        "VORTEX_LINE_URL": "http://127.0.0.1:1",
        "VORTEX_BOARD_PORT": str(port),
        "VORTEX_CALLS_LOG": str(log_path),
        "VORTEX_ENV": "production",
        "VORTEX_OPS_PASSWORD": "test-password",
        "VORTEX_STORAGE_SECRET": "test-session-secret",
        "NICEGUI_STORAGE_PATH": str(tmp_path / "storage"),
    }
    # This subprocess runs the actual app, not NiceGUI's browser-test harness.
    env.pop("PYTEST_CURRENT_TEST", None)
    root = Path(__file__).resolve().parents[1]
    process = subprocess.Popen(
        [sys.executable, "-m", "vortex.observability.live"],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.communicate()[0].decode(errors="replace")
                pytest.fail(f"Board exited before startup: {output}")
            try:
                if httpx.get(url + "/wall", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        else:
            pytest.fail("Board did not start in time")
        yield url, log_path
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()


def test_public_overview_links_to_live_updating_call_placeholder(board_url):
    url, path = board_url
    response = httpx.get(url + "/wall")
    assert response.status_code == 200
    # NiceGUI embeds its generated elements in the initial HTML. Unicode may be
    # JSON-escaped, so use ASCII headings and call IDs for these route assertions.
    assert "LLAMADAS EN CURSO" in response.text
    assert "IDENTIFYING" in response.text
    assert "OFFERING" in response.text
    assert "FINISHED" in response.text
    assert "100%" in response.text
    assert "finished-call" in response.text
    query = urlencode({"call_id": "demo-call & special"})
    assert query in response.text
    detail = httpx.get(url + "/wall/call?" + query)
    assert detail.status_code == 200
    assert "PLACEHOLDER" in detail.text
    assert "OFFERING" in detail.text

    # A subsequent request reflects new events, including a closed socket.
    log = CallLog("demo-call & special", path)
    log.event("call.ended")
    detail = httpx.get(url + "/wall/call?" + query)
    assert "FINISHED" in detail.text
    assert "SIN RESULTADO" in detail.text

    # Public pages stay accessible even with production ops authentication.
    private = httpx.get(url + "/")
    assert "Vortex ops" in private.text
    assert "Replay book" not in private.text
    missing = httpx.get(url + "/wall/call?call_id=not-present")
    assert missing.status_code == 200
    assert "PLACEHOLDER" in missing.text
    assert "not-present" in missing.text
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(events) == 7  # Viewing pages never fabricates call events.
