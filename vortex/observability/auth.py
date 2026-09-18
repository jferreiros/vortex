from __future__ import annotations

import hmac
import os
import time
from collections import defaultdict

_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
_WINDOW_S = 600.0
_MAX_ATTEMPTS = 8


def ops_password() -> str:
    return os.environ.get("VORTEX_OPS_PASSWORD", "").strip()


def is_production() -> bool:
    return os.environ.get("VORTEX_ENV", "").strip().lower() in {"production", "prod"}


def must_authenticate() -> bool:
    return bool(ops_password()) or is_production()


def storage_secret() -> str:
    secret = os.environ.get("VORTEX_STORAGE_SECRET", "").strip()
    if secret:
        return secret
    if is_production():
        raise RuntimeError("VORTEX_STORAGE_SECRET is required in production")
    return "vortex-board-dev"


def check_password(candidate: str) -> bool:
    expected = ops_password()
    if not expected:
        return not is_production()
    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


def login_allowed(ip: str) -> bool:
    now = time.time()
    recent = [t for t in _ATTEMPTS[ip] if now - t < _WINDOW_S]
    _ATTEMPTS[ip] = recent
    return len(recent) < _MAX_ATTEMPTS


def record_login_attempt(ip: str) -> None:
    _ATTEMPTS[ip].append(time.time())
