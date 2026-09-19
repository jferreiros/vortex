"""Audio helpers: PCM, WAV, noise at a fixed SNR, word/entity error rates.

Everything is 16-bit mono PCM. The line is 8 kHz µ-law; providers are fed
16 kHz WAV (Deepgram, OpenAI, Cartesia and Soniox all accept it) after the same
8 kHz round trip the platform imposes, so what they hear is what a call
sounds like.
"""

from __future__ import annotations

import io
import math
import re
import struct
import unicodedata
import wave

import numpy as np

REFERENCE_DBFS = -20.0  # the challenge's noise spec: signal at -20 dBFS
PEAK_CAP_DBFS = -6.0  # noise peaks capped at -6 dBFS
NOISE_SNR_DB = 5.0  # problem 12


def pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        fh.writeframes(pcm)
    return buf.getvalue()


def wav_to_pcm(data: bytes) -> tuple[bytes, int]:
    with wave.open(io.BytesIO(data), "rb") as fh:
        assert fh.getnchannels() == 1 and fh.getsampwidth() == 2
        return fh.readframes(fh.getnframes()), fh.getframerate()


def resample(pcm: bytes, rate_in: int, rate_out: int) -> bytes:
    if rate_in == rate_out:
        return pcm
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    n_out = int(round(len(x) * rate_out / rate_in))
    if n_out <= 0:
        return b""
    xp = np.linspace(0, len(x) - 1, num=n_out)
    y = np.interp(xp, np.arange(len(x)), x)
    return np.clip(y, -32768, 32767).astype(np.int16).tobytes()


def telephone_round_trip(pcm: bytes, rate: int) -> bytes:
    """Down to 8 kHz and back: the band the µ-law line leaves. Same rate out."""
    return resample(resample(pcm, rate, 8000), 8000, rate)


def _rms_dbfs(x: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0
    return 20 * math.log10(max(rms, 1e-9) / 32768.0)


def normalise_to(pcm: bytes, target_dbfs: float = REFERENCE_DBFS) -> bytes:
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if not len(x):
        return pcm
    gain = 10 ** ((target_dbfs - _rms_dbfs(x)) / 20)
    return np.clip(x * gain, -32768, 32767).astype(np.int16).tobytes()


def add_noise(pcm: bytes, rate: int, snr_db: float = NOISE_SNR_DB, seed: int = 12) -> bytes:
    """Mix pink-ish noise at ``snr_db`` below a -20 dBFS signal, peaks capped at -6 dBFS."""
    signal = np.frombuffer(normalise_to(pcm), dtype=np.int16).astype(np.float32)
    if not len(signal):
        return pcm
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(len(signal)).astype(np.float32)
    # Cheap pink: a first-order low-pass over white noise (street/room rumble).
    pink = np.empty_like(white)
    acc = 0.0
    for i, w in enumerate(white):
        acc = 0.98 * acc + 0.02 * w
        pink[i] = acc * 8 + w * 0.3
    target_noise_dbfs = REFERENCE_DBFS - snr_db
    gain = 10 ** ((target_noise_dbfs - _rms_dbfs(pink)) / 20)
    pink *= gain
    cap = 32768.0 * 10 ** (PEAK_CAP_DBFS / 20)
    pink = np.clip(pink, -cap, cap)
    return np.clip(signal + pink, -32768, 32767).astype(np.int16).tobytes()


def synthetic_voice(text: str, rate: int = 16000, seed: int = 3) -> bytes:
    """A deterministic speech-like waveform, ~14 chars per second. For the fake provider."""
    seconds = max(0.6, len(text) / 14.0)
    n = int(seconds * rate)
    t = np.arange(n) / rate
    rng = np.random.default_rng(seed + sum(map(ord, text)) % 997)
    f0 = 120 + 40 * rng.random()
    env = 0.5 * (1 + np.sin(2 * np.pi * 3.5 * t + rng.random() * 6.28))  # syllable rate
    voice = (
        np.sin(2 * np.pi * f0 * t)
        + 0.5 * np.sin(2 * np.pi * 2 * f0 * t)
        + 0.25 * np.sin(2 * np.pi * 3 * f0 * t)
    )
    x = voice * env * 0.3 * 32767
    return x.astype(np.int16).tobytes()


def duration_s(pcm: bytes, rate: int) -> float:
    return len(pcm) / 2 / rate


def pcm16_to_ulaw_bytes(pcm: bytes) -> bytes:
    """8-bit µ-law from 16-bit PCM (G.711), for on-the-wire size estimates."""
    out = bytearray()
    for (sample,) in struct.iter_unpack("<h", pcm):
        sign = 0x80 if sample < 0 else 0
        mag = min(abs(sample) + 0x84, 0x7FFF)
        exp = 7
        mask = 0x4000
        while exp > 0 and not mag & mask:
            exp -= 1
            mask >>= 1
        mant = (mag >> (exp + 3)) & 0x0F
        out.append(~(sign | (exp << 4) | mant) & 0xFF)
    return bytes(out)


# ---- word error rate --------------------------------------------------------

_NUM_WORDS = {
    "cero": "0",
    "uno": "1",
    "una": "1",
    "u": "1",  # Catalan
    "dos": "2",
    "tres": "3",
    "quatre": "4",  # Catalan
    "cuatro": "4",
    "cinco": "5",
    "cinc": "5",  # Catalan
    "seis": "6",
    "sis": "6",  # Catalan
    "siete": "7",
    "set": "7",  # Catalan
    "ocho": "8",
    "vuit": "8",  # Catalan
    "nueve": "9",
}

# Spoken letter names for DNI/NIE check letters (Spanish + common Catalan).
_LETTER_WORDS = {
    "a": "a",
    "be": "b",
    "ce": "c",
    "de": "d",
    "e": "e",
    "efe": "f",
    "ge": "g",
    "hache": "h",
    "i": "i",
    "jota": "j",
    "ka": "k",
    "ele": "l",
    "eme": "m",
    "ene": "n",
    "enie": "n",
    "eñe": "n",
    "o": "o",
    "pe": "p",
    "cu": "q",
    "erre": "r",
    "ese": "s",
    "te": "t",
    "u": "u",
    "uve": "v",
    "equis": "x",
    "ye": "y",
    "zeta": "z",
}

_EMAIL_SPOKEN = (
    ("guion bajo", "_"),
    ("arroba", "@"),
    ("at", "@"),
    ("punto", "."),
    ("punt", "."),
    ("dot", "."),
    ("guion", "-"),
)

ENTITY_KINDS = ("name", "dni", "phone", "email")


def normalise_text(text: str) -> list[str]:
    """Lower-case, strip accents and punctuation, spell digits as words consistently."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9ñç\s]", " ", text)
    words = text.split()
    return [_NUM_WORDS.get(w, w) for w in words]


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref, hyp = normalise_text(reference), normalise_text(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    d = list(range(len(hyp) + 1))
    for i in range(1, len(ref) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(hyp) + 1):
            cur = d[j]
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + cost)
            prev = cur
    return d[len(hyp)] / len(ref)


def char_error_rate(reference: str, hypothesis: str) -> float:
    ref = " ".join(normalise_text(reference))
    hyp = " ".join(normalise_text(hypothesis))
    return _edit_rate(ref, hyp)


def _edit_rate(ref: str, hyp: str) -> float:
    if not ref:
        return 0.0 if not hyp else 1.0
    d = list(range(len(hyp) + 1))
    for i in range(1, len(ref) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(hyp) + 1):
            cur = d[j]
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + cost)
            prev = cur
    return d[len(hyp)] / len(ref)


def _best_window_cer(ref: str, haystack: str) -> float:
    """Character error rate of ``ref`` against the best contiguous window of ``haystack``."""
    if not ref:
        return 0.0 if not haystack else 1.0
    if ref in haystack:
        return 0.0
    best = _edit_rate(ref, haystack)
    n = len(ref)
    lo, hi = max(1, n // 2), max(n, len(haystack))
    for win in range(lo, hi + 1):
        if win > len(haystack):
            break
        for i in range(0, len(haystack) - win + 1):
            best = min(best, _edit_rate(ref, haystack[i : i + win]))
            if best == 0.0:
                return 0.0
    return best


def _fold_email_spoken(text: str) -> str:
    out = text.lower()
    for spoken, symbol in _EMAIL_SPOKEN:
        out = re.sub(rf"(?<![a-z0-9]){re.escape(spoken)}(?![a-z0-9])", symbol, out)
    return out


def compact_entity(kind: str, text: str) -> str:
    """Canonical form of an entity for character-level scoring."""
    if kind == "email":
        folded = _fold_email_spoken(text)
        folded = unicodedata.normalize("NFKD", folded.lower())
        folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
        return re.sub(r"\s+", "", folded)
    words = normalise_text(text)
    if kind == "name":
        return " ".join(words)
    mapped: list[str] = []
    for w in words:
        if w in _LETTER_WORDS:
            mapped.append(_LETTER_WORDS[w])
        else:
            mapped.append(w)
    joined = "".join(mapped)
    if kind == "dni":
        return re.sub(r"[^0-9a-z]", "", joined)
    if kind == "phone":
        digits = re.sub(r"\D", "", joined)
        if digits.startswith("34") and len(digits) > 9:
            digits = digits[2:]
        return digits[-9:] if len(digits) >= 9 else digits
    return joined


def entity_char_error_rate(kind: str, reference: str, hypothesis: str) -> float:
    """CER of one entity value against the best span in the transcript.

    ``kind`` is one of ``name``, ``dni``, ``phone``, ``email``. Digits spoken
    as words and DNI letter names are folded before the edit distance runs, so
    a perfect read-back scores zero even when the STT writes Arabic numerals.
    """
    assert kind in ENTITY_KINDS, f"unknown entity kind {kind!r}"
    ref = compact_entity(kind, reference)
    hyp = compact_entity(kind, hypothesis)
    return _best_window_cer(ref, hyp)


def entity_cers(entities: dict[str, str], hypothesis: str) -> dict[str, float]:
    """CER per annotated entity present on an utterance."""
    return {
        kind: entity_char_error_rate(kind, value, hypothesis)
        for kind, value in entities.items()
        if kind in ENTITY_KINDS and value
    }
