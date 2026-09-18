"""G.711 µ-law helpers, pure Python. Enough for test tones and silence.

The real voice pipeline lets pipecat convert audio. This module exists so the
stub pipeline, the smoke test and the fake caller need no audio dependency.
"""

from __future__ import annotations

import math

_BIAS = 0x84
_CLIP = 32635
SILENCE_BYTE = 0xFF  # µ-law encoding of 0


def _encode_sample(sample: int) -> int:
    sign = 0
    if sample < 0:
        sign = 0x80
        sample = -sample
    if sample > _CLIP:
        sample = _CLIP
    sample += _BIAS
    exponent = 7
    mask = 0x4000
    while exponent > 0 and not (sample & mask):
        exponent -= 1
        mask >>= 1
    mantissa = (sample >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


def _decode_sample(byte: int) -> int:
    byte = ~byte & 0xFF
    sign = byte & 0x80
    exponent = (byte >> 4) & 0x07
    mantissa = byte & 0x0F
    sample = ((mantissa << 3) + _BIAS) << exponent
    sample -= _BIAS
    return -sample if sign else sample


def pcm16_to_ulaw(pcm: bytes) -> bytes:
    """Little-endian signed 16-bit mono -> µ-law bytes."""
    out = bytearray(len(pcm) // 2)
    for i in range(len(out)):
        sample = int.from_bytes(pcm[2 * i : 2 * i + 2], "little", signed=True)
        out[i] = _encode_sample(sample)
    return bytes(out)


def ulaw_to_pcm16(ulaw: bytes) -> bytes:
    out = bytearray(len(ulaw) * 2)
    for i, byte in enumerate(ulaw):
        out[2 * i : 2 * i + 2] = _decode_sample(byte).to_bytes(2, "little", signed=True)
    return bytes(out)


def tone(freq_hz: float, ms: int, *, sample_rate: int = 8000, amplitude: float = 0.4) -> bytes:
    """A sine tone as µ-law bytes."""
    n = sample_rate * ms // 1000
    peak = int(32767 * amplitude)
    pcm = bytearray()
    for i in range(n):
        value = int(peak * math.sin(2 * math.pi * freq_hz * i / sample_rate))
        pcm += value.to_bytes(2, "little", signed=True)
    return pcm16_to_ulaw(bytes(pcm))


def silence(ms: int, *, sample_rate: int = 8000) -> bytes:
    return bytes([SILENCE_BYTE]) * (sample_rate * ms // 1000)
