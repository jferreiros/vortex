"""Voice bench wiring: Soniox stack, entity CER, offline fake path."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from evals.voice import audio
from evals.voice.providers import make_stt
from evals.voice.runner import load_pricing, load_utterances, run_all


def test_pricing_lists_soniox_stt_rt_v5_stack() -> None:
    pricing = load_pricing()
    assert "soniox_stt_rt_v5" in pricing["stt"]
    assert pricing["stt"]["soniox_stt_rt_v5"]["usd_per_min"] == 0.002
    names = {s["name"] for s in pricing["stacks"]}
    assert "soniox-41mini-oai" in names
    soniox = next(s for s in pricing["stacks"] if s["name"] == "soniox-41mini-oai")
    assert soniox["stt"] == "soniox_stt_rt_v5"


def test_utterances_cover_name_dni_phone_email_entities() -> None:
    doc = load_utterances()
    kinds: set[str] = set()
    for u in doc["utterances"]:
        kinds.update((u.get("entities") or {}).keys())
    assert kinds >= {"name", "dni", "phone", "email"}


def test_make_stt_soniox_uses_fake_offline() -> None:
    stt = make_stt("soniox_stt_rt_v5", real=False)
    assert stt.simulated is True
    assert stt.supports("es")
    assert stt.supports("ca")


def test_make_stt_soniox_real_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SONIOX_API_KEY", raising=False)
    stt = make_stt("soniox_stt_rt_v5", real=True)
    assert stt.simulated is False
    pcm = audio.synthetic_voice("hola")
    result = asyncio.run(stt.transcribe(pcm, 16000, "es"))
    assert result.error
    assert "SONIOX_API_KEY" in (result.error or "")


def test_fake_soniox_stack_reports_entity_cer_at_5db(tmp_path: Path) -> None:
    run = asyncio.run(run_all(real=False, stacks="soniox-41mini-oai", results_dir=tmp_path))
    assert run.summary["stacks"], "expected one stack row"
    row = run.summary["stacks"][0]
    assert row["name"] == "soniox-41mini-oai"
    assert row["stt"] == "soniox_stt_rt_v5"
    assert "noisy" in row["wer"]
    noisy = row["entity_cer_noisy"]
    for kind in ("name", "dni", "phone", "email"):
        assert kind in noisy
        assert noisy[kind] is not None
    noisy_cases = [c for c in run.cases if c.id.endswith(".noisy") and c.status == "pass"]
    assert any(c.extra.get("entity_cer") for c in noisy_cases)
