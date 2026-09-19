"""The hosted call log stays off unless both keys are set, and a test tmp
file never becomes a network read.
"""

from __future__ import annotations

import json
from pathlib import Path

from vortex.observability import supabase_log
from vortex.observability.calllog import CallLog, read_calls, read_recent
from vortex.settings import reset_settings


def test_event_hash_is_order_independent() -> None:
    a = {"kind": "call.started", "call_id": "C1", "ts": "t"}
    b = {"ts": "t", "call_id": "C1", "kind": "call.started"}
    assert supabase_log.event_hash(a) == supabase_log.event_hash(b)


def test_unconfigured_without_keys(monkeypatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    reset_settings()
    assert supabase_log.configured() is False
    assert supabase_log.ping()["ok"] is False
    supabase_log.enqueue({"kind": "x", "ts": "t", "call_id": "C"})  # no-op
    reset_settings()


def test_read_helpers_stay_on_tmp_file_even_if_keys_present(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "calls.jsonl"
    log = CallLog("CA-test", path)
    log.event("call.started", from_number="+34600000000")
    log.event("call.ended", reason="hangup")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    reset_settings()
    assert supabase_log.uses_this_log(path) is False
    recent = read_recent(path, limit=10)
    assert [e["kind"] for e in recent] == ["call.started", "call.ended"]
    grouped, meta = read_calls(path, max_calls=5)
    assert meta["calls"] == 1
    assert "CA-test" in grouped
    # The writer still produced JSON-safe lines locally.
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[0])["call_id"] == "CA-test"
    reset_settings()


def test_product_db_path_defaults_to_the_repo_logs(monkeypatch, tmp_path: Path) -> None:
    from database import remote

    monkeypatch.delenv("VORTEX_PRODUCT_DB", raising=False)
    default = remote.product_db_path()
    assert default.name == "vortex_product.db"
    assert default.parent.name == "logs"
    monkeypatch.setenv("VORTEX_PRODUCT_DB", str(tmp_path / "other.db"))
    assert remote.product_db_path() == (tmp_path / "other.db").resolve()
