from __future__ import annotations

from vortex.observability import auth


def test_open_when_no_password_outside_production(monkeypatch) -> None:
    monkeypatch.delenv("VORTEX_OPS_PASSWORD", raising=False)
    monkeypatch.delenv("VORTEX_ENV", raising=False)
    assert auth.must_authenticate() is False
    assert auth.check_password("anything") is True


def test_password_compare(monkeypatch) -> None:
    monkeypatch.setenv("VORTEX_OPS_PASSWORD", "team-secret")
    monkeypatch.delenv("VORTEX_ENV", raising=False)
    assert auth.must_authenticate() is True
    assert auth.check_password("team-secret") is True
    assert auth.check_password("nope") is False


def test_production_requires_password(monkeypatch) -> None:
    monkeypatch.setenv("VORTEX_ENV", "production")
    monkeypatch.delenv("VORTEX_OPS_PASSWORD", raising=False)
    assert auth.must_authenticate() is True
    assert auth.check_password("") is False


def test_login_rate_limit(monkeypatch) -> None:
    auth._ATTEMPTS.clear()
    ip = "203.0.113.9"
    for _ in range(8):
        assert auth.login_allowed(ip) is True
        auth.record_login_attempt(ip)
    assert auth.login_allowed(ip) is False
