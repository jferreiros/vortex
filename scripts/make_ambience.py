"""Generate looping 8 kHz mono office bed + keyboard overlay.

Prefers real CC0 recordings (Joseph Sardin / BigSoundBank), resampled to
8 kHz mono and overlap-added so the wrap stays at the same level.
The office bed is a quiet clinic room: HVAC + distant typing + paper.
``typing.wav`` is close keys only — the mixer keeps the office bed under it.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf

SEED = 20260920
SAMPLE_RATE = 8000
OFFICE_SECONDS = 8.0
TYPING_SECONDS = 6.0
CROSSFADE_MS = 80
OFFICE_CROSSFADE_MS = 450
# CC0 (public domain): https://bigsoundbank.com/computer-keyboard-s0229.html
TYPING_SOURCE_URL = "https://bigsoundbank.com/UPLOAD/bwf-en/0229.wav"
# CC0 HVAC room: https://bigsoundbank.com/air-conditioner-s1471.html
OFFICE_HVAC_URL = "https://bigsoundbank.com/UPLOAD/bwf-en/1471.wav"
# CC0 distant desks: https://bigsoundbank.com — Quick Keyboard #1734
OFFICE_KEYS_URL = "https://bigsoundbank.com/UPLOAD/bwf-en/1734.wav"
# CC0 paper: workbook #0786
OFFICE_PAPER_URL = "https://bigsoundbank.com/UPLOAD/bwf-en/0786.wav"


def _dbfs_peak(x: np.ndarray, dbfs: float) -> np.ndarray:
    peak = float(np.max(np.abs(x))) or 1.0
    return x * (10.0 ** (dbfs / 20.0) / peak)


def _dbfs_rms(x: np.ndarray, dbfs: float) -> np.ndarray:
    rms = float(np.sqrt(np.mean(x**2))) or 1.0
    return x * (10.0 ** (dbfs / 20.0) / rms)


def _fft_band(x: np.ndarray, sr: int, *, low: float | None, high: float | None) -> np.ndarray:
    n = len(x)
    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    gain = np.ones_like(spectrum, dtype=np.float64)
    if high is not None:
        roll = max(high * 0.2, 40.0)
        gain *= np.clip((high + roll - freqs) / (2.0 * roll), 0.0, 1.0)
    if low is not None:
        roll = max(low * 0.2, 40.0)
        gain *= np.clip((freqs - (low - roll)) / (2.0 * roll), 0.0, 1.0)
    return np.fft.irfft(spectrum * gain, n=n)


def _crossfade_loop(x: np.ndarray, sr: int, fade_ms: float = CROSSFADE_MS) -> np.ndarray:
    """Equal-power overlap-add so sample 0 follows the last sample without a dip."""
    n = min(int(sr * fade_ms / 1000.0), len(x) // 4)
    if n < 2 or len(x) <= n:
        return x
    t = np.linspace(0.0, np.pi / 2.0, n, dtype=np.float64)
    fade_out = np.cos(t)
    fade_in = np.sin(t)
    out = x[n:].copy()
    out[-n:] = x[-n:] * fade_out + x[:n] * fade_in
    return out


def office_bed(n: int, sr: int, rng: np.random.Generator) -> np.ndarray:
    """HVAC room: brown/pink rumble under ~700 Hz, not hiss."""
    t = np.arange(n) / sr
    brown = np.cumsum(rng.standard_normal(n))
    brown -= brown.mean()
    rumble = _dbfs_peak(_fft_band(brown, sr, low=None, high=450.0), 0.0)

    pink_spec = np.fft.rfft(rng.standard_normal(n))
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    pink_spec /= np.maximum(np.sqrt(freqs), 1.0)
    pink = np.fft.irfft(pink_spec, n=n)
    pink = _dbfs_peak(_fft_band(pink, sr, low=None, high=700.0), 0.0)

    hum = np.sin(2.0 * np.pi * 120.0 * t) + 0.22 * np.sin(2.0 * np.pi * 240.0 * t)
    wobble = 0.88 + 0.12 * np.sin(2.0 * np.pi * 0.16 * t)
    return (0.70 * rumble + 0.22 * pink + 0.10 * hum) * wobble


def _key_click(sr: int, rng: np.random.Generator) -> np.ndarray:
    """Laptop/membrane key: filtered-noise clack, not a sine blip."""
    n = max(10, int(sr * rng.uniform(0.007, 0.014)))
    noise = rng.standard_normal(n)
    i = np.arange(n)
    clack = _fft_band(noise * np.exp(-i / (0.0018 * sr)), sr, low=650.0, high=2100.0)
    body = _fft_band(noise * np.exp(-i / (0.007 * sr)), sr, low=140.0, high=520.0)
    return (0.72 * clack + 0.38 * body) * rng.uniform(0.45, 1.0)


def _spacebar(sr: int, rng: np.random.Generator) -> np.ndarray:
    n = max(16, int(sr * rng.uniform(0.018, 0.032)))
    noise = rng.standard_normal(n)
    i = np.arange(n)
    body = _fft_band(noise * np.exp(-i / (0.011 * sr)), sr, low=80.0, high=380.0)
    shell = _fft_band(noise * np.exp(-i / (0.004 * sr)), sr, low=400.0, high=900.0)
    return (0.8 * body + 0.2 * shell) * rng.uniform(0.4, 0.75)


def typing_clicks(n: int, sr: int, rng: np.random.Generator) -> np.ndarray:
    """Hunt-and-peck on a clinic PC: short bursts, then a pause, ~5 keys/s."""
    out = np.zeros(n, dtype=np.float64)
    margin = int(0.06 * sr)
    t = margin / sr
    end = (n - margin) / sr
    while t < end:
        if rng.random() < 0.14:
            t += rng.uniform(0.22, 0.55)
            continue
        burst = int(rng.integers(2, 6))
        for k in range(burst):
            start = int(t * sr)
            if start >= n - margin:
                break
            click = _key_click(sr, rng)
            stop = min(n, start + len(click))
            out[start:stop] += click[: stop - start]
            t += rng.uniform(0.07, 0.16)
            if k + 1 < burst and rng.random() < 0.12:
                t += rng.uniform(0.03, 0.06)
        t += rng.uniform(0.12, 0.28)

    st = rng.uniform(0.6, 1.4)
    while st < end:
        start = int(st * sr)
        thump = _spacebar(sr, rng)
        stop = min(n, start + len(thump))
        out[start:stop] += thump[: stop - start]
        st += rng.uniform(1.2, 2.2)
    return out


def _resample(x: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate or len(x) < 2:
        return x
    n = max(2, int(round(len(x) * dst_rate / src_rate)))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)


def _densest_window(x: np.ndarray, sr: int, seconds: float) -> np.ndarray:
    win = int(seconds * sr)
    if len(x) <= win:
        return x
    hop = max(1, int(0.1 * sr))
    best_i, best_e = 0, -1.0
    for i in range(0, len(x) - win + 1, hop):
        chunk = x[i : i + win]
        energy = float(np.dot(chunk, chunk))
        if energy > best_e:
            best_i, best_e = i, energy
    return x[best_i : best_i + win]


def render_typing_from_recording(path: Path, sr: int) -> np.ndarray:
    data, rate = sf.read(path, dtype="float64")
    if data.ndim > 1:
        data = data.mean(axis=1)
    data = _densest_window(data, rate, TYPING_SECONDS + 0.25)
    # Drop the room captured with the keys; our office loop already has that.
    data = _fft_band(data, rate, low=280.0, high=None)
    data = _resample(data, rate, sr)[: int(sr * TYPING_SECONDS)]
    return _dbfs_peak(_crossfade_loop(data, sr), -8.0)


def _steadiest_window(x: np.ndarray, sr: int, seconds: float) -> np.ndarray:
    """Pick a loop that does not jump in level (room tone, not a loud event)."""
    win = int(seconds * sr)
    if len(x) <= win:
        return x
    hop = max(1, int(0.2 * sr))
    frame = max(1, int(0.05 * sr))
    best_i, best_var = 0, float("inf")
    for i in range(0, len(x) - win + 1, hop):
        chunk = x[i : i + win]
        rms = [
            float(np.sqrt(np.mean(chunk[j : j + frame] ** 2)))
            for j in range(0, len(chunk) - frame, frame)
        ]
        var = float(np.var(rms)) if rms else float("inf")
        if var < best_var:
            best_i, best_var = i, var
    return x[best_i : best_i + win]


def _mid_energy_window(x: np.ndarray, sr: int, seconds: float) -> np.ndarray:
    """Typical activity, not the loudest burst and not a quiet gap."""
    win = int(seconds * sr)
    if len(x) <= win:
        return x
    hop = max(1, int(0.2 * sr))
    scores: list[tuple[float, int]] = []
    for i in range(0, len(x) - win + 1, hop):
        scores.append((float(np.mean(x[i : i + win] ** 2)), i))
    target = float(np.median([energy for energy, _ in scores]))
    start = min(scores, key=lambda item: abs(item[0] - target))[1]
    return x[start : start + win]


def _read_mono(path: Path) -> tuple[np.ndarray, int]:
    data, rate = sf.read(path, dtype="float64")
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data, int(rate)


def _trim_edges(x: np.ndarray, sr: int, seconds: float = 1.0) -> np.ndarray:
    n = int(seconds * sr)
    if len(x) <= 2 * n + sr:
        return x
    return x[n:-n]


def _even_level(x: np.ndarray, sr: int, win_s: float = 0.3) -> np.ndarray:
    """Hold room tone at a steady loudness so the bed cannot fall into a hole."""
    win = max(16, int(win_s * sr))
    kernel = np.ones(win, dtype=np.float64) / win
    env = np.sqrt(np.convolve(x * x, kernel, mode="same") + 1e-12)
    target = float(np.median(env))
    return x * (target / np.maximum(env, target / 6.0))


def _prepare_layer(
    path: Path,
    sr: int,
    seconds: float,
    *,
    low: float,
    high: float,
    picker,
) -> np.ndarray:
    data, rate = _read_mono(path)
    data = _trim_edges(data, rate)
    data = picker(data, rate, seconds + 0.05)
    data = _fft_band(data, rate, low=low, high=high)
    return _resample(data, rate, sr)[: int(sr * seconds)]


def render_office_from_recordings(
    hvac_path: Path,
    sr: int,
    *,
    keys_path: Path | None = None,
    paper_path: Path | None = None,
) -> np.ndarray:
    seconds = OFFICE_SECONDS + OFFICE_CROSSFADE_MS / 1000.0
    hvac = _even_level(
        _prepare_layer(hvac_path, sr, seconds, low=40.0, high=900.0, picker=_steadiest_window),
        sr,
    )
    mix = _dbfs_rms(hvac, -18.0)
    if keys_path is not None:
        keys = _prepare_layer(
            keys_path, sr, seconds, low=350.0, high=2200.0, picker=_mid_energy_window
        )
        mix = mix + 0.16 * _dbfs_peak(keys, -12.0)
    if paper_path is not None:
        paper = _prepare_layer(
            paper_path, sr, seconds, low=180.0, high=1800.0, picker=_mid_energy_window
        )
        mix = mix + 0.07 * _dbfs_peak(paper, -14.0)
    looped = _crossfade_loop(mix, sr, fade_ms=OFFICE_CROSSFADE_MS)
    return np.clip(_dbfs_rms(looped, -20.0), -1.0, 1.0)


def fetch_source(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 10_000:
        return dest
    urllib.request.urlretrieve(url, dest)
    return dest


def render_office(sr: int, rng: np.random.Generator) -> np.ndarray:
    n = int(sr * OFFICE_SECONDS)
    return _dbfs_peak(
        _crossfade_loop(office_bed(n, sr, rng), sr, fade_ms=OFFICE_CROSSFADE_MS), -10.0
    )


def render_typing(sr: int, rng: np.random.Generator) -> np.ndarray:
    n = int(sr * TYPING_SECONDS)
    clicks = typing_clicks(n, sr, rng)
    return _dbfs_peak(_crossfade_loop(clicks, sr), -6.0)


def to_int16(x: np.ndarray) -> np.ndarray:
    return np.round(np.clip(x, -1.0, 1.0) * 32767.0).astype(np.int16)


def write_sounds(dest: Path, *, seed: int = SEED, sr: int = SAMPLE_RATE) -> tuple[Path, Path]:
    dest.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    office_path = dest / "office.wav"
    typing_path = dest / "typing.wav"
    office = None
    try:
        hvac = fetch_source(OFFICE_HVAC_URL, Path("/tmp/vortex-ac-1471.wav"))
        keys = None
        paper = None
        try:
            keys = fetch_source(OFFICE_KEYS_URL, Path("/tmp/vortex-kb-1734.wav"))
        except Exception as exc:
            print(f"distant keyboard skipped ({exc})")
        try:
            paper = fetch_source(OFFICE_PAPER_URL, Path("/tmp/vortex-paper-0786.wav"))
        except Exception as exc:
            print(f"paper rustle skipped ({exc})")
        office = render_office_from_recordings(hvac, sr, keys_path=keys, paper_path=paper)
        print("office.wav from CC0 HVAC + distant keys + paper")
    except Exception as exc:
        print(f"office.wav synthetic fallback ({exc})")
        office = render_office(sr, rng)
    sf.write(office_path, to_int16(office), sr, subtype="PCM_16")
    typing = None
    try:
        raw = Path("/tmp/vortex-kb-0229.wav")
        fetch_source(TYPING_SOURCE_URL, raw)
        typing = render_typing_from_recording(raw, sr)
        print("typing.wav from CC0 recording (BigSoundBank #0229)")
    except Exception as exc:
        print(f"typing.wav synthetic fallback ({exc})")
        typing = render_typing(sr, rng)
    sf.write(typing_path, to_int16(typing), sr, subtype="PCM_16")
    return office_path, typing_path


def main() -> None:
    dest = Path(__file__).resolve().parents[1] / "vortex" / "line" / "sounds"
    for path in write_sounds(dest):
        print(f"{path} {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
