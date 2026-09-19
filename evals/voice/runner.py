"""The provider matrix: same utterances, every stack, one table.

For each stack in ``pricing.yaml`` and each utterance in ``utterances.yaml``:

1. **Caller audio.** Synthesised once per utterance by the *caller voice*
   (OpenAI TTS when real, since it is the only one claiming gl/eu; the fake
   voice otherwise), passed through the 8 kHz telephone round trip, cached
   under ``results/voice/audio``. A noisy twin is mixed at 5 dB SNR (problem 12).
2. **STT.** The stack's transcriber hears clean and noisy. WER against the
   reference, plus entity CER (name, DNI, phone, email) when the utterance
   annotates them. ``final_ms`` is the wait after the audio ends.
3. **LLM.** One short receptionist reply; TTFT is what matters.
4. **TTS.** The reply is spoken; TTFB is what the caller hears first.

Perceived latency = STT final + LLM TTFT + TTS TTFB, per utterance; p50 and
p95 across utterances. Cost per call comes from the call profile in
``pricing.yaml`` times each stack's unit prices, then times 68 for a Run All
and times the weekend plan.

The brake: before any real call the run estimates its own cost from the same
table and refuses above ``--max-eur``. Every real run appends to
``results/voice/spend.json`` so the running total is one file away.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import statistics
import time
from pathlib import Path
from typing import Any

import yaml

from evals.common.results import RESULTS_DIR, CaseResult, RunResult, git_info, now_stamp
from evals.voice import audio
from evals.voice.providers import make_llm, make_stt, make_tts

HERE = Path(__file__).resolve().parent
PRICING = HERE / "pricing.yaml"
UTTERANCES = HERE / "utterances.yaml"


def load_pricing() -> dict[str, Any]:
    return yaml.safe_load(PRICING.read_text())


def load_utterances() -> dict[str, Any]:
    return yaml.safe_load(UTTERANCES.read_text())


# ---- cost model ---------------------------------------------------------------


def stack_cost_per_call(stack: dict[str, Any], pricing: dict[str, Any]) -> dict[str, float]:
    """Euros for one 3-minute call, by stage, from list prices and the call profile."""
    p = pricing["call_profile"]
    eur = pricing["eur_per_usd"]
    stt = pricing["stt"][stack["stt"]]
    tts = pricing["tts"][stack["tts"]]
    llm = pricing["llm"][stack["llm"]]
    stt_min = p["duration_min"] if stt.get("bills") == "socket" else p["caller_speech_min"]
    stt_rate = stt.get("usd_per_min") or stt.get("usd_per_min_effective") or 0.0
    stt_usd = stt_min * stt_rate
    tts_usd = p["agent_chars"] / 1000 * tts.get("usd_per_1k_chars", 0.0) + p[
        "agent_speech_min"
    ] * tts.get("usd_per_min_audio", 0.0)
    llm_usd = p["llm_input_tokens"] / 1e6 * llm.get("usd_per_1m_input", 0.0) + p[
        "llm_output_tokens"
    ] / 1e6 * llm.get("usd_per_1m_output", 0.0)
    total = (stt_usd + tts_usd + llm_usd) * eur
    return {
        "stt_eur": stt_usd * eur,
        "llm_eur": llm_usd * eur,
        "tts_eur": tts_usd * eur,
        "total_eur": total,
    }


def estimate_run_cost(
    stacks: list[dict[str, Any]], utterances: list[dict[str, Any]], pricing: dict[str, Any]
) -> float:
    """What this benchmark run itself will spend, in euros, at list prices."""
    eur = pricing["eur_per_usd"]
    agent_reply_chars = 120
    total = 0.0
    caller_tts = pricing["tts"]["openai_gpt4o_mini_tts"]
    for u in utterances:
        seconds = max(1.0, len(u["text"]) / 14.0)
        total += seconds / 60 * caller_tts.get("usd_per_min_audio", 0.0) * eur  # caller audio, once
        for stack in stacks:
            stt = pricing["stt"][stack["stt"]]
            rate = stt.get("usd_per_min") or stt.get("usd_per_min_effective") or 0.0
            total += 2 * seconds / 60 * rate * eur  # clean + noisy
            llm = pricing["llm"][stack["llm"]]
            total += (
                400 / 1e6 * llm.get("usd_per_1m_input", 0)
                + 40 / 1e6 * llm.get("usd_per_1m_output", 0)
            ) * eur
            tts = pricing["tts"][stack["tts"]]
            total += (
                agent_reply_chars / 1000 * tts.get("usd_per_1k_chars", 0.0)
                + 0.1 * tts.get("usd_per_min_audio", 0.0)
            ) * eur
    return total


# ---- the run ------------------------------------------------------------------


def _p(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return float(statistics.quantiles(values, n=100, method="inclusive")[int(q * 100) - 1])


async def _caller_audio(u: dict[str, Any], real: bool, cache: Path) -> tuple[bytes, int] | None:
    """Synthesise (or load) the caller's utterance: 16 kHz PCM after the phone round trip."""
    cache.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1((u["text"] + ("real" if real else "fake")).encode()).hexdigest()[:10]
    path = cache / f"{u['id']}-{digest}.wav"
    if path.exists():
        pcm, rate = audio.wav_to_pcm(path.read_bytes())
        return pcm, rate
    voice = make_tts("openai_gpt4o_mini_tts", real=real)
    res = await voice.synthesize(u["text"], u["language"])
    if not res.supported or res.error or not res.pcm:
        return None
    pcm = audio.resample(res.pcm, res.rate, 16000)
    pcm = audio.telephone_round_trip(pcm, 16000)
    path.write_bytes(audio.pcm_to_wav(pcm, 16000))
    return pcm, 16000


async def run_all(
    *,
    real: bool = False,
    stacks: str | None = None,
    max_eur: float = 0.5,
    languages: str | None = None,
    results_dir: Path = RESULTS_DIR,
) -> RunResult:
    pricing = load_pricing()
    doc = load_utterances()
    utterances = doc["utterances"]
    if languages:
        wanted = {x.strip() for x in languages.split(",")}
        utterances = [u for u in utterances if u["language"] in wanted]
    chosen = pricing["stacks"]
    if stacks:
        names = {x.strip() for x in stacks.split(",")}
        chosen = [s for s in chosen if s["name"] in names]
    run = RunResult(
        layer="voice",
        started_at=now_stamp(),
        mode={
            "providers": "real" if real else "fake",
            "max_eur": max_eur,
            "stacks": [s["name"] for s in chosen],
        },
        git=git_info(),
    )
    estimate = estimate_run_cost(chosen, utterances, pricing)
    run.summary["estimated_run_cost_eur"] = estimate
    if real and estimate > max_eur:
        run.notes.append(
            f"REFUSED: this run is estimated at {estimate:.3f} € at list prices, "
            f"above --max-eur {max_eur:.2f}. "
            "Raise the cap or pick fewer stacks/languages."
        )
        run.cases.append(
            CaseResult(
                id="voice.budget_brake",
                name="budget brake",
                status="skipped",
                details=[run.notes[-1]],
            )
        )
        return run
    if not real:
        run.notes.append(
            "SIMULATED: fake provider. Latencies and WER are invented to exercise the report. "
            "Costs are real list prices from pricing.yaml."
        )
    started = time.monotonic()
    cache = results_dir / "voice" / "audio"
    caller: dict[str, tuple[bytes, int]] = {}
    for u in utterances:
        got = await _caller_audio(u, real, cache)
        if got is None:
            run.cases.append(
                CaseResult(
                    id=f"caller_audio.{u['id']}",
                    name=u["id"],
                    status="skipped",
                    details=["caller voice could not synthesise this language"],
                )
            )
            continue
        caller[u["id"]] = got

    system = "Eres la recepcionista de Clínica Arenal. Responde en una frase."
    table: list[dict[str, Any]] = []
    spent = 0.0
    for stack in chosen:
        stt = make_stt(stack["stt"], real=real)
        tts = make_tts(stack["tts"], real=real)
        llm = make_llm(stack["llm"], real=real)
        e2e: list[float] = []
        stt_ms: list[float] = []
        llm_ms: list[float] = []
        tts_ms: list[float] = []
        wer_by: dict[str, list[float]] = {}
        entity_cer_by: dict[str, list[float]] = {k: [] for k in audio.ENTITY_KINDS}
        entity_cer_noisy: dict[str, list[float]] = {k: [] for k in audio.ENTITY_KINDS}
        stack_ok = True
        for u in utterances:
            if u["id"] not in caller:
                continue
            pcm, rate = caller[u["id"]]
            for variant, sample in (("clean", pcm), ("noisy", audio.add_noise(pcm, rate))):
                case = CaseResult(
                    id=f"{stack['name']}.{u['id']}.{variant}",
                    name=f"{stack['name']} · {u['id']} · {variant}",
                    status="error",
                    group=stack["name"],
                    tags=[u["language"], variant],
                )
                t = await stt.transcribe(
                    sample, rate, u["language"], hint=f"[{variant}] {u['text']}"
                )
                if not t.supported:
                    case.status = "skipped"
                    case.details.append(f"{stack['stt']} does not support {u['language']}")
                    run.cases.append(case)
                    wer_by.setdefault(u["language"], [])
                    continue
                if t.error:
                    case.details.append(f"STT error: {t.error}")
                    stack_ok = False
                    run.cases.append(case)
                    continue
                wer = audio.word_error_rate(u["text"], t.text)
                wer_by.setdefault(u["language"], []).append(wer)
                wer_by.setdefault(variant, []).append(wer)
                entities = u.get("entities") or {}
                entity_scores = audio.entity_cers(entities, t.text) if entities else {}
                for kind, cer in entity_scores.items():
                    entity_cer_by[kind].append(cer)
                    if variant == "noisy":
                        entity_cer_noisy[kind].append(cer)
                reply = await llm.reply(system, doc["agent_prompt"])
                s = await tts.synthesize(reply.text or doc["agent_reply_reference"], "es")
                if reply.error or s.error:
                    case.details.append(f"LLM/TTS error: {reply.error or s.error}")
                    stack_ok = False
                    run.cases.append(case)
                    continue
                perceived = t.final_ms + reply.ttft_ms + s.ttfb_ms
                e2e.append(perceived)
                stt_ms.append(t.final_ms)
                llm_ms.append(reply.ttft_ms)
                tts_ms.append(s.ttfb_ms)
                case.status = "pass" if wer <= 0.35 else "fail"
                detail = (
                    f"WER {wer * 100:.0f}% · STT {t.final_ms:.0f} ms · TTFT {reply.ttft_ms:.0f} ms "
                    f"· TTFB {s.ttfb_ms:.0f} ms · perceived {perceived:.0f} ms"
                )
                if entity_scores:
                    cer_bits = " · ".join(
                        f"CER {kind} {cer * 100:.0f}%" for kind, cer in entity_scores.items()
                    )
                    detail += f" · {cer_bits}"
                case.details.append(detail)
                if wer > 0.35:
                    case.details.append(f"heard: {t.text!r}")
                case.extra = {
                    "wer": wer,
                    "entity_cer": entity_scores,
                    "heard": t.text,
                    "stt_ms": t.final_ms,
                    "ttft_ms": reply.ttft_ms,
                    "ttfb_ms": s.ttfb_ms,
                }
                case.duration_ms = int(t.final_ms + reply.total_ms + s.total_ms)
                if real:
                    stt_row = pricing["stt"][stack["stt"]]
                    rate_usd = (
                        stt_row.get("usd_per_min") or stt_row.get("usd_per_min_effective") or 0.0
                    )
                    case.cost_eur = (
                        t.audio_s / 60 * rate_usd
                        + s.chars / 1000 * pricing["tts"][stack["tts"]].get("usd_per_1k_chars", 0.0)
                        + audio.duration_s(s.pcm, s.rate)
                        / 60
                        * pricing["tts"][stack["tts"]].get("usd_per_min_audio", 0.0)
                        + reply.tokens_in
                        / 1e6
                        * pricing["llm"][stack["llm"]].get("usd_per_1m_input", 0.0)
                        + reply.tokens_out
                        / 1e6
                        * pricing["llm"][stack["llm"]].get("usd_per_1m_output", 0.0)
                    ) * pricing["eur_per_usd"]
                    spent += case.cost_eur
                run.cases.append(case)
        per_call = stack_cost_per_call(stack, pricing)
        prof = pricing["call_profile"]
        weekend_calls = (
            prof["calls_per_run_all"] * prof["weekend_run_alls"] + prof["weekend_practice_calls"]
        )

        def wer_avg(key: str, by: dict[str, list[float]] = wer_by) -> float | None:
            vals = by.get(key)
            return round(sum(vals) / len(vals), 3) if vals else None

        def cer_avg(by: dict[str, list[float]], kind: str) -> float | None:
            vals = by.get(kind) or []
            return round(sum(vals) / len(vals), 3) if vals else None

        table.append(
            {
                "name": stack["name"],
                "describe": stack.get("describe", ""),
                "stt": stack["stt"],
                "llm": stack["llm"],
                "tts": stack["tts"],
                "ok": stack_ok,
                "e2e_p50_ms": _p(e2e, 0.5),
                "e2e_p95_ms": _p(e2e, 0.95),
                "stt_p50_ms": _p(stt_ms, 0.5),
                "llm_ttft_p50_ms": _p(llm_ms, 0.5),
                "tts_ttfb_p50_ms": _p(tts_ms, 0.5),
                "wer": {k: wer_avg(k) for k in ("es", "ca", "gl", "eu", "clean", "noisy")},
                "entity_cer": {k: cer_avg(entity_cer_by, k) for k in audio.ENTITY_KINDS},
                "entity_cer_noisy": {k: cer_avg(entity_cer_noisy, k) for k in audio.ENTITY_KINDS},
                "cost_per_call_eur": per_call["total_eur"],
                "cost_breakdown_eur": per_call,
                "cost_68_calls_eur": per_call["total_eur"] * prof["calls_per_run_all"],
                "cost_weekend_eur": per_call["total_eur"] * weekend_calls,
                "languages_stt": pricing["stt"][stack["stt"]].get("languages", []),
                "languages_tts": pricing["tts"][stack["tts"]].get("languages", []),
            }
        )
    table.sort(key=lambda s: s["e2e_p50_ms"] or 1e9)
    run.summary["stacks"] = table
    run.summary["simulated"] = not real
    run.summary["call_profile"] = pricing["call_profile"]
    run.summary["pricing_read_on"] = pricing.get("read_on")
    run.cost_eur = spent
    run.duration_ms = int((time.monotonic() - started) * 1000)
    if real:
        _record_spend(results_dir, spent, run.started_at)
    cheapest = min(table, key=lambda s: s["cost_per_call_eur"]) if table else None
    fastest = table[0] if table else None
    if cheapest and fastest:
        run.notes.append(
            f"Fastest perceived: {fastest['name']} (p50 {fastest['e2e_p50_ms']:.0f} ms). "
            f"Cheapest: {cheapest['name']} "
            f"({cheapest['cost_68_calls_eur']:.2f} € per 68-call Run All)."
        )
    return run


def _record_spend(results_dir: Path, spent: float, when: str) -> None:
    path = results_dir / "voice" / "spend.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(path.read_text()) if path.exists() else {"total_eur": 0.0, "runs": []}
    data["total_eur"] = round(data["total_eur"] + spent, 4)
    data["runs"].append({"at": when, "eur": round(spent, 4)})
    path.write_text(json.dumps(data, indent=1))


def run_sync(**kwargs: Any) -> RunResult:
    return asyncio.run(run_all(**kwargs))
