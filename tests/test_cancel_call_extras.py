"""The cancel-rebooking extras: phone normalisation and the fallback env."""

import pytest

from vortex.line.confirmation_calls import normalise_call_phone
import vortex.settings as settings_module


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("612345678", "+34612345678"),          # national mobile
        ("612 34 56 78", "+34612345678"),       # separators
        ("912 345 678", "+34912345678"),        # national landline
        ("0034 612 345 678", "+34612345678"),   # international prefix
        ("+34 612 345 678", "+34612345678"),    # already E.164
        ("+44 7700 900123", "+447700900123"),   # other countries honoured
        ("", ""),                               # nothing to fix
        ("12345", "12345"),                     # unknown shape: cleaned, unprefixed
    ],
)
def test_normalise_call_phone(raw: str, expected: str) -> None:
    assert normalise_call_phone(raw) == expected


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("VORTEX_CANCEL_CALL_FALLBACK_TO", raising=False)
    settings_module.reset_settings()
    yield monkeypatch
    settings_module.reset_settings()


def test_fallback_recipient_defaults_empty(clean_env) -> None:
    assert settings_module.get_settings().cancel_call_fallback_to == ""


def test_fallback_recipient_reads_env(clean_env) -> None:
    clean_env.setenv("VORTEX_CANCEL_CALL_FALLBACK_TO", "+34600000000")
    settings_module.reset_settings()
    assert settings_module.get_settings().cancel_call_fallback_to == "+34600000000"
