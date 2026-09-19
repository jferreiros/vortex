from __future__ import annotations

import os
from typing import Any

import httpx

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"
TIMEOUT_S = 2.5


class JevError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        raise JevError("TYPESAFE_API_KEY is missing")
    return key


async def ask(state: str | dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
    payload = {"model": MODEL, "state": state, "questions": questions}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            response = await client.post(
                ENDPOINT,
                json=payload,
                headers={
                    "Authorization": f"Bearer {_api_key()}",
                    "Content-Type": "application/json",
                },
            )
    except httpx.HTTPError as exc:
        raise JevError(f"request failed: {exc}") from exc
    if response.status_code >= 400:
        raise JevError(f"HTTP {response.status_code}: {response.text[:240]}")
    body = response.json()
    if not isinstance(body, dict):
        raise JevError("response was not an object")
    return body


def noul(body: dict[str, Any], name: str) -> float | None:
    block = _named(body, name)
    if not block:
        return None
    value = block.get("noul")
    return float(value) if value is not None else None


def _named(body: dict[str, Any], name: str) -> dict[str, Any] | None:
    answers = body.get("answers")
    if isinstance(answers, dict) and name in answers:
        block = answers[name]
        return block if isinstance(block, dict) else None
    bucket = body.get("nouls")
    if isinstance(bucket, dict) and name in bucket:
        block = bucket[name]
        return block if isinstance(block, dict) else None
    return None
