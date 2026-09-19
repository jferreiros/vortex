from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"
TIMEOUT_S = 8.0


class JevError(RuntimeError):
    pass


@dataclass(frozen=True)
class JevAnswer:
    raw: dict[str, Any]
    latency_ms: int
    model: str

    def choice(self, name: str) -> str | None:
        block = self._named(name)
        if not block:
            return None
        return block.get("choice")

    def noul(self, name: str) -> float | None:
        block = self._named(name)
        if not block:
            return None
        value = block.get("noul")
        return float(value) if value is not None else None

    def confidence(self, name: str) -> float | None:
        block = self._named(name)
        if not block:
            return None
        value = block.get("confidence")
        return float(value) if value is not None else None

    def _named(self, name: str) -> dict[str, Any] | None:
        answers = self.raw.get("answers")
        if isinstance(answers, dict) and name in answers:
            block = answers[name]
            return block if isinstance(block, dict) else None
        for group in ("choices", "nouls", "scores"):
            bucket = self.raw.get(group)
            if isinstance(bucket, dict) and name in bucket:
                block = bucket[name]
                return block if isinstance(block, dict) else None
        return None


def _api_key() -> str:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        raise JevError("TYPESAFE_API_KEY is missing")
    return key


def ask(state: str | dict[str, Any], questions: dict[str, Any]) -> JevAnswer:
    payload = {"model": MODEL, "state": state, "questions": questions}
    started = time.perf_counter()
    try:
        response = httpx.post(
            ENDPOINT,
            json=payload,
            headers={
                "Authorization": f"Bearer {_api_key()}",
                "Content-Type": "application/json",
            },
            timeout=TIMEOUT_S,
        )
    except httpx.HTTPError as exc:
        raise JevError(f"request failed: {exc}") from exc
    latency_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code >= 400:
        raise JevError(f"HTTP {response.status_code}: {response.text[:400]}")
    body = response.json()
    if not isinstance(body, dict):
        raise JevError("response was not an object")
    return JevAnswer(
        raw=body,
        latency_ms=latency_ms,
        model=str(body.get("model") or MODEL),
    )
