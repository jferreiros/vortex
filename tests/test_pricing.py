"""The price table turns metered counters into euros, and says when it cannot.

Every number here is checked against the table in ``vortex/observability/
pricing.py``, so a price change breaks the test that quotes it, not a screen.
"""

from __future__ import annotations

from typing import Any

import pytest

from vortex.observability import pricing


def _usage(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "metered": True,
        "stt": {"provider": "soniox", "model": "stt-rt-v5", "audio_seconds": 60.0, "requests": 12},
        "llm": {
            "provider": "helmcode",
            "model": "deepseek-v4-flash",
            "prompt_tokens": 1_000_000,
            "completion_tokens": 1_000_000,
            "reasoning_tokens": 0,
            "cache_read_input_tokens": 0,
            "requests": 7,
        },
        "tts": [
            {
                "provider": "elevenlabs",
                "service": "ElevenLabsTTSService",
                "model": "eleven_flash_v2_5",
                "characters": 1_000_000,
                "requests": 6,
            }
        ],
    }
    base.update(over)
    return base


def test_the_eur_rate_is_the_bench_table_not_a_second_one() -> None:
    """One rate for the whole repo. The mirror exists only for the board image."""
    from evals.bench.pricing import eur_per_usd as bench_rate

    assert pricing.eur_per_usd() == bench_rate()
    assert pricing.EUR_PER_USD_FALLBACK == bench_rate()


def test_soniox_seconds_become_euros_at_the_listed_rate() -> None:
    cost = pricing.price_call(_usage())
    # $0.12/hour = $0.002/minute, one minute of audio.
    assert cost.stt_eur == pytest.approx(0.002 * pricing.eur_per_usd())
    assert cost.stt_seconds == 60.0


def test_an_unknown_stt_model_is_unpriced_not_free() -> None:
    usage = _usage(stt={"provider": "deepgram", "model": "nova-3", "audio_seconds": 60.0})
    cost = pricing.price_call(usage)
    assert cost.stt_eur == 0.0
    assert cost.priced is False
    assert cost.partial is True
    assert "STT deepgram/nova-3" in cost.unpriced


def test_helmcode_llm_is_a_perk_so_we_pay_nothing_at_the_margin() -> None:
    cost = pricing.price_call(_usage())
    # DeepSeek list price: $0.14 in + $0.28 out per 1M tokens.
    assert cost.llm_list_eur == pytest.approx((0.14 + 0.28) * pricing.eur_per_usd())
    assert cost.llm_eur == 0.0
    assert cost.perk is True
    assert cost.total_eur < cost.total_list_eur


def test_a_perk_model_with_no_list_price_is_still_free_but_partial() -> None:
    """Qwen is unlimited inside the perk and has no published per-token rate."""
    usage = _usage(
        llm={
            "provider": "helmcode",
            "model": "qwen3.6",
            "prompt_tokens": 12_000,
            "completion_tokens": 600,
        }
    )
    cost = pricing.price_call(usage)
    assert cost.llm_eur == 0.0
    assert cost.llm_list_eur == 0.0
    assert cost.unpriced == ["LLM helmcode/qwen3.6", "TTS eleven_flash_v2_5"]
    assert cost.priced is False


def test_the_perk_is_decided_by_the_provider_not_by_the_model() -> None:
    """Swap the provider and the same tokens stop being free, whatever the model."""
    usage = _usage(
        llm={
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "prompt_tokens": 12_000,
            "completion_tokens": 600,
        }
    )
    cost = pricing.price_call(usage)
    assert cost.perk is False
    assert cost.llm_eur == cost.llm_list_eur
    assert cost.unpriced == ["LLM openai/gpt-4.1-mini", "TTS eleven_flash_v2_5"]


def test_tts_voices_match_by_substring() -> None:
    """One row per model family, matched on a prefix of the reported model id."""
    assert pricing.tts_price("eleven_flash_v2_5") is pricing.TTS_PRICES[0][1]
    assert pricing.tts_price("eleven_multilingual_v2") is pricing.TTS_PRICES[0][1]
    # A model outside the table is unpriced, not free.
    assert pricing.tts_price("es-ES-Wavenet-B") is None


def test_elevenlabs_is_in_the_table_without_a_price() -> None:
    for voice in ("eleven_flash_v2_5", "eleven_multilingual_v2"):
        row = pricing.tts_price(voice)
        assert row is not None, voice
        assert row["usd"] is None, voice
        assert row["source"]


def test_a_partial_call_still_sums_the_legs_it_could_price() -> None:
    """The TTS leg has no verified list price; STT and the LLM still count."""
    usage = _usage(
        tts=[
            {
                "provider": "elevenlabs",
                "service": "ElevenLabsTTSService",
                "model": "eleven_flash_v2_5",
                "characters": 1_000_000,
            },
            {
                "provider": "elevenlabs",
                "service": "ElevenLabsTTSService",
                "model": "eleven_multilingual_v2",
                "characters": 90,
            },
        ]
    )
    cost = pricing.price_call(usage)
    assert cost.tts_eur == 0.0
    assert cost.tts_characters == 1_000_090
    assert cost.unpriced == ["TTS eleven_flash_v2_5", "TTS eleven_multilingual_v2"]
    assert cost.priced is False
    # Soniox and the LLM list price are both verified, so the total is not zero.
    assert cost.total_list_eur > 0


def test_reasoning_and_cached_tokens_are_a_breakdown_not_extra_tokens() -> None:
    """They are subsets of the totals the provider reports, so they add nothing."""
    plain = pricing.price_call(_usage())
    detailed = pricing.price_call(
        _usage(
            llm={
                "provider": "helmcode",
                "model": "deepseek-v4-flash",
                "prompt_tokens": 1_000_000,
                "completion_tokens": 1_000_000,
                "reasoning_tokens": 400_000,
                "cache_read_input_tokens": 700_000,
            }
        )
    )
    assert detailed.llm_list_eur == plain.llm_list_eur


def test_a_stub_call_is_not_metered_and_never_counts_as_free() -> None:
    stub = pricing.price_call({"metered": False, "stt": {}, "llm": {}, "tts": []})
    assert stub.metered is False
    assert stub.priced is False
    assert stub.total_list_eur == 0.0


def test_a_call_with_no_usage_event_at_all_is_not_metered() -> None:
    for missing in (None, {}, "nope", []):
        cost = pricing.price_call(missing)
        assert cost.metered is False
        assert cost.priced is False


def test_zero_counters_do_not_flag_a_leg_as_unpriced() -> None:
    """A call that never reached TTS is not a call with an unknown TTS price."""
    usage = _usage(
        stt={"provider": "soniox", "model": "stt-rt-v5", "audio_seconds": 0.0},
        llm={"provider": "helmcode", "model": "deepseek-v4-flash", "prompt_tokens": 0},
        tts=[],
    )
    cost = pricing.price_call(usage)
    assert cost.unpriced == []
    assert cost.priced is True
    assert cost.total_list_eur == 0.0


def test_every_priced_row_names_where_the_number_came_from() -> None:
    rows = [*pricing.STT_PRICES.values(), *pricing.LLM_PRICES.values()]
    rows += [row for _, row in pricing.TTS_PRICES]
    for row in rows:
        assert row["source"].startswith("https://"), row
        assert row["read_on"]


def test_formatting_is_euros_and_grouped_counts() -> None:
    assert pricing.eur(0.03562) == "€0.0356"
    assert pricing.eur(0.03562, 2) == "€0.04"
    assert pricing.eur(None) == "—"
    assert pricing.count(11840) == "11 840"
