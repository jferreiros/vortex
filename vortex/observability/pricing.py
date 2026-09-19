"""What one call costs, from the provider counters the line lane meters.

The line lane writes one ``call.usage`` event per call, just before
``call.ended``: seconds of audio through Soniox, tokens through Helmcode, and
characters through each Google TTS service. This module turns those counters
into euros with an explicit price table. Nothing here estimates: a model with
no verified price is *unpriced*, the call is flagged ``partial``, and the
console says so instead of showing a made-up number.

Two numbers come out of every call, and both are shown:

- **list price** — what the call would cost anyone at the vendors' published
  rates. This is the jury number.
- **what we pay** — the same sum with the LLM leg at zero, because Helmcode is
  a hackathon perk: a flat monthly fee, no marginal cost per token. The list
  price is still computed, for the day the perk ends.

Token semantics follow the OpenAI-compatible wire shape the providers use:
``reasoning_tokens`` is a breakdown of ``completion_tokens`` and
``cache_read_input_tokens`` a breakdown of ``prompt_tokens``, so billing adds
neither on top. Cached input has its own rate at some vendors; none of the
models we run publishes one we have verified, so it is billed as plain input.

Prices were read on 2026-09-19. Each row carries its ``source``: change the
number here, and every screen recomputes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

READ_ON = "2026-09-19"

#: The one EUR/USD rate lives in ``evals/bench/models.yaml`` and is read
#: through ``evals.bench.pricing.eur_per_usd()``. The board's container image
#: ships ``vortex/`` only (see Dockerfile.board.dockerignore), so ``evals`` is
#: not importable there — this constant mirrors the table for that case alone.
#: ``tests/test_pricing.py`` fails when the two drift apart.
EUR_PER_USD_FALLBACK = 0.92


def eur_per_usd() -> float:
    """The EUR/USD rate the bench tables use. Never a second rate of our own."""
    try:
        from evals.bench.pricing import eur_per_usd as bench_rate

        return float(bench_rate())
    except Exception:
        return EUR_PER_USD_FALLBACK


# ---------------------------------------------------------------------------
# The price table
# ---------------------------------------------------------------------------

#: Speech to text, keyed ``provider/model``. ``usd`` is per unit.
STT_PRICES: dict[str, dict[str, Any]] = {
    "soniox/stt-rt-v5": {
        "label": "Soniox stt-rt-v5 (real-time)",
        "usd": 0.002,
        "unit": "minute of audio",  # $0.12 per hour
        "source": "https://soniox.com/pricing",
        "read_on": READ_ON,
    },
}

#: Text to speech. Voices are matched by substring against the voice or model
#: id, first match wins, so a whole Google voice family is one row. ``usd:
#: None`` means the vendor publishes no price we have verified.
TTS_PRICES: tuple[tuple[str, dict[str, Any]], ...] = (
    (
        "Chirp3-HD",
        {
            "label": "Google Cloud TTS · Chirp 3 HD",
            "usd": 30.0,
            "unit": "1M characters",
            "source": "https://cloud.google.com/text-to-speech/pricing",
            "read_on": READ_ON,
        },
    ),
    (
        "Standard",
        {
            "label": "Google Cloud TTS · Standard",
            "usd": 4.0,
            "unit": "1M characters",
            "source": "https://cloud.google.com/text-to-speech/pricing",
            "read_on": READ_ON,
        },
    ),
    (
        "gemini-",
        {
            "label": "Google Gemini TTS",
            "usd": None,
            "unit": "1M characters",
            "source": "https://cloud.google.com/text-to-speech/pricing",
            "read_on": READ_ON,
            "note": "Gemini TTS is not on the published character table; unverified.",
        },
    ),
    (
        "eleven_",
        {
            "label": "ElevenLabs Flash v2.5",
            "usd": None,
            "unit": "1M characters",
            "source": "https://elevenlabs.io/pricing",
            "read_on": READ_ON,
            "note": "Credit-based plans, no verified per-character list price.",
        },
    ),
)

#: Large language models, keyed ``provider/model`` the way
#: ``evals/bench/models.yaml`` keys them. ``usd_in``/``usd_out`` are the
#: vendor's own list price per 1M tokens, kept even for a perk model.
LLM_PRICES: dict[str, dict[str, Any]] = {
    "helmcode/deepseek-v4-flash": {
        "label": "DeepSeek V4 Flash (via Helmcode)",
        "usd_in": 0.14,
        "usd_out": 0.28,
        "unit": "1M tokens",
        "source": "https://pricepertoken.com/pricing-page/model/deepseek-deepseek-v4-flash",
        "read_on": READ_ON,
        "note": "DeepSeek's own API list price; the counterfactual for the perk.",
    },
    "helmcode/qwen3.6": {
        "label": "Qwen 3.6 (via Helmcode)",
        "usd_in": None,
        "usd_out": None,
        "unit": "1M tokens",
        "source": "https://helmcode.com/pricing",
        "read_on": READ_ON,
        "note": "Unlimited inside the perk; no published per-token list price.",
    },
}

#: Providers whose marginal cost to us is zero. Helmcode bills a flat monthly
#: fee per API key, so the tokens themselves are free at the margin.
PERK_PROVIDERS = frozenset({"helmcode"})

PERK_SOURCE = "https://helmcode.com/pricing"


@dataclass
class CallCost:
    """One call in euros. ``*_eur`` is what we pay, ``*_list_eur`` list price."""

    stt_eur: float = 0.0
    llm_eur: float = 0.0
    llm_list_eur: float = 0.0
    tts_eur: float = 0.0
    total_eur: float = 0.0
    total_list_eur: float = 0.0
    #: True when every leg with a non-zero counter had a verified price.
    priced: bool = False
    #: True when the call carried a ``call.usage`` event with real counters.
    #: A call from the stub lane, or an old call logged before metering, is
    #: not metered and stays out of every average.
    metered: bool = False
    #: Human labels for the legs we could not price, for the caption.
    unpriced: list[str] = field(default_factory=list)
    #: True when the LLM leg is a perk, so "we pay" is below list price.
    perk: bool = False
    #: The raw counters, for the per-call breakdown.
    stt_seconds: float = 0.0
    llm_tokens_in: int = 0
    llm_tokens_out: int = 0
    tts_characters: int = 0

    @property
    def partial(self) -> bool:
        return self.metered and not self.priced


def _spec_id(leg: dict[str, Any]) -> str:
    provider = str(leg.get("provider") or "?")
    model = str(leg.get("model") or "?")
    return f"{provider}/{model}"


def tts_price(voice: str) -> dict[str, Any] | None:
    """The row whose key is a substring of ``voice``. None when nothing matches."""
    for needle, row in TTS_PRICES:
        if needle in voice:
            return row
    return None


def price_call(usage: Any) -> CallCost:
    """Price one ``call.usage`` payload. Anything else is an unmetered call."""
    if not isinstance(usage, dict) or not usage.get("metered"):
        return CallCost()

    rate = eur_per_usd()
    cost = CallCost(metered=True)
    unpriced: list[str] = []

    stt = usage.get("stt") if isinstance(usage.get("stt"), dict) else {}
    seconds = float(stt.get("audio_seconds") or 0.0)
    cost.stt_seconds = seconds
    if seconds > 0:
        row = STT_PRICES.get(_spec_id(stt))
        if row is None or row.get("usd") is None:
            unpriced.append(f"STT {_spec_id(stt)}")
        else:
            cost.stt_eur = seconds / 60.0 * float(row["usd"]) * rate

    llm = usage.get("llm") if isinstance(usage.get("llm"), dict) else {}
    tokens_in = int(llm.get("prompt_tokens") or 0)
    tokens_out = int(llm.get("completion_tokens") or 0)
    cost.llm_tokens_in = tokens_in
    cost.llm_tokens_out = tokens_out
    cost.perk = str(llm.get("provider") or "") in PERK_PROVIDERS
    if tokens_in or tokens_out:
        row = LLM_PRICES.get(_spec_id(llm))
        if row is None or row.get("usd_in") is None or row.get("usd_out") is None:
            unpriced.append(f"LLM {_spec_id(llm)}")
        else:
            usd = tokens_in / 1e6 * float(row["usd_in"]) + tokens_out / 1e6 * float(row["usd_out"])
            cost.llm_list_eur = usd * rate
    cost.llm_eur = 0.0 if cost.perk else cost.llm_list_eur

    legs = usage.get("tts") if isinstance(usage.get("tts"), list) else []
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        characters = int(leg.get("characters") or 0)
        cost.tts_characters += characters
        if characters <= 0:
            continue
        voice = str(leg.get("model") or leg.get("service") or "")
        row = tts_price(voice)
        if row is None or row.get("usd") is None:
            unpriced.append(f"TTS {voice or '?'}")
        else:
            cost.tts_eur += characters / 1e6 * float(row["usd"]) * rate

    cost.unpriced = unpriced
    cost.priced = not unpriced
    cost.total_list_eur = cost.stt_eur + cost.llm_list_eur + cost.tts_eur
    cost.total_eur = cost.stt_eur + cost.llm_eur + cost.tts_eur
    return cost


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def eur(value: float | None, places: int = 4) -> str:
    """'€0.0356'. An em dash when there is no number to show."""
    if value is None:
        return "—"
    return f"€{value:.{places}f}"


def count(value: float | int) -> str:
    """11840 -> '11 840'. Thin grouping, the way the tables show numbers."""
    return f"{int(value):,}".replace(",", " ")
