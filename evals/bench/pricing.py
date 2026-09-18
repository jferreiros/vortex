"""Prices for the models the bench and the model brain talk to.

Two tables feed this: ``evals/bench/models.yaml`` (by ``provider/model`` id)
and, as a fallback for bare OpenAI names, the ``llm`` block of
``evals/voice/pricing.yaml``. A model with no verified price costs 0 here and
the report says "n/a", never a made-up number.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
MODELS_YAML = HERE / "models.yaml"
VOICE_PRICING = HERE.parent / "voice" / "pricing.yaml"


@functools.lru_cache(maxsize=1)
def catalogue() -> dict[str, Any]:
    return yaml.safe_load(MODELS_YAML.read_text()) or {}


def entries() -> list[dict[str, Any]]:
    return list(catalogue().get("models") or [])


def entry(spec_id: str) -> dict[str, Any] | None:
    for row in entries():
        if row.get("id") == spec_id:
            return row
    return None


def eur_per_usd() -> float:
    return float(catalogue().get("eur_per_usd", 0.92))


def price_usd(spec_id: str) -> tuple[float, float] | None:
    """(usd per 1M input, usd per 1M output) or None when unverified."""
    row = entry(spec_id)
    if row is not None:
        if row.get("usd_per_1m_input") is None or row.get("usd_per_1m_output") is None:
            return None
        return float(row["usd_per_1m_input"]), float(row["usd_per_1m_output"])
    # Bare OpenAI names live in the voice table.
    model = spec_id.split("/", 1)[1] if "/" in spec_id else spec_id
    try:
        llm = (yaml.safe_load(VOICE_PRICING.read_text()) or {}).get("llm") or {}
    except OSError:
        return None
    voice_row = llm.get(model)
    if not voice_row or "usd_per_1m_input" not in voice_row:
        return None
    return float(voice_row["usd_per_1m_input"]), float(voice_row["usd_per_1m_output"])


def is_perk(spec_id: str) -> bool:
    row = entry(spec_id)
    return bool(row and row.get("billing") == "perk")


def cost_eur(spec_id: str, tokens_in: int, tokens_out: int) -> float:
    """What those tokens cost in euros at list price. 0 for a perk or an unknown price."""
    if is_perk(spec_id):
        return 0.0
    prices = price_usd(spec_id)
    if prices is None:
        return 0.0
    usd = tokens_in / 1e6 * prices[0] + tokens_out / 1e6 * prices[1]
    return usd * eur_per_usd()


def list_cost_per_call_eur(spec_id: str) -> float | None:
    """€ for one scored call at list price from the call profile. None when unverified.

    A perk model still gets its list price here when one is known: this is
    the number for the day the perk ends.
    """
    prices = price_usd(spec_id)
    if prices is None:
        return None
    profile = catalogue().get("call_profile") or {}
    tokens_in = float(profile.get("llm_input_tokens", 12000))
    tokens_out = float(profile.get("llm_output_tokens", 600))
    usd = tokens_in / 1e6 * prices[0] + tokens_out / 1e6 * prices[1]
    return usd * eur_per_usd()
