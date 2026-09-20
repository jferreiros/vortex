"""Render the talking page-intro clip: Vorty on pure white, waving, with an
English voice-over.

Two steps, one command:
  1. A silent clip via fal-ai/kling-video/o1/reference-to-video — Vorty walks
     in on a pure-white cyclorama, waves hello and tilts its head as if
     greeting. It has no mouth (black visor), so there is no lip-sync; the
     "speaking" is carried entirely by the voice-over.
  2. An English voice-over via fal-ai/minimax/speech-02-hd.
Then ffmpeg muxes the voice onto the clip, holding on screen for 2 extra
seconds after the voice ends (silent tail).

Both stills of the "Vorty" character in vortex/wall/media/reference/ are
uploaded once and referenced as @Image1 / @Image2 for a consistent design.

Requires ffmpeg on PATH and:
    export FAL_KEY=...   # from fal.ai dashboard - never commit it

Usage:
    uv run --with fal-client python scripts/video/generate_intro_v4.py
    uv run --with fal-client python scripts/video/generate_intro_v4.py --aspect-ratio 9:16
    uv run --with fal-client python scripts/video/generate_intro_v4.py --keep-parts
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import fal_client
import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REFERENCE_DIR = REPO_ROOT / "vortex" / "wall" / "media" / "reference"
DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "output"

# Order matters: first upload becomes @Image1, second becomes @Image2.
IMAGE_FILES = ["avatar2d.png", "Unknown.jpg"]

VIDEO_MODEL = "fal-ai/kling-video/o1/reference-to-video"
TTS_MODEL = "fal-ai/minimax/speech-02-hd"

# What Vorty says. Kept as the single source of truth so the clip length and
# the voice match.
SPEECH = (
    "Hola, soy Vorti, un agente de voz creado por el equipo Vortex "
    "en HackSpain que agenda citas médicas."
)

# Seconds to keep the clip on screen after the voice-over ends (silent tail).
SILENT_TAIL_SECONDS = 2.0

VIDEO_PROMPT = (
    "Continuous single wide shot, static camera. Background: pure solid flat "
    "white, hex FFFFFF, no gradient, no grey tint, no shadows on the "
    "background, infinite white studio cyclorama, stays pure white FFFFFF for "
    "the whole clip. Soft cinematic lighting, 35mm lens, one continuous shot, "
    "no on-screen text, no UI overlays, no captions, no icons, no readable "
    "words anywhere. Keep the character's design matching @Image1 and "
    "@Image2: a small round white robot receptionist named Vorty, glossy "
    "plastic, black rounded visor face (no mouth), green headset with boom "
    "mic, black blazer, grey clipboard. Action, one smooth continuous take "
    "with varied, natural gestures, never repeating the same motion: Vorty "
    "walks in from the left with a confident little bounce, stops centered "
    "facing the camera, gives one warm quick wave hello, then lowers the hand "
    "and lets go of the wave. From there it presents itself expressively as if "
    "explaining: gesturing with open hands, tapping and holding up its "
    "clipboard, pointing lightly toward the camera, giving a small friendly "
    "thumbs up, tilting and nodding its head, adjusting its headset once, and "
    "shifting its weight with lively body language. Keep the gestures flowing "
    "and different from each other, energetic but calm, always keeping eye "
    "contact with the camera. No mouth movement, no speech bubbles, no "
    "captions, no readable text or letter-like symbols anywhere."
)


def on_queue_update(update: object) -> None:
    if isinstance(update, fal_client.InProgress):
        for log in update.logs:
            print(log["message"])


def upload_reference_images() -> list[str]:
    urls = []
    for filename in IMAGE_FILES:
        path = REFERENCE_DIR / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing reference image: {path}")
        print(f"Uploading {filename}...")
        urls.append(fal_client.upload_file(str(path)))
    return urls


def _download(url: str, dest: Path) -> None:
    with httpx.stream("GET", url, follow_redirects=True) as response:
        response.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)


def generate_video(image_urls: list[str], dest: Path, aspect_ratio: str) -> None:
    print("\n=== Generating silent clip ===")
    result = fal_client.subscribe(
        VIDEO_MODEL,
        arguments={
            "prompt": VIDEO_PROMPT,
            "image_urls": image_urls,
            "duration": "10",
            "aspect_ratio": aspect_ratio,
        },
        with_logs=True,
        on_queue_update=on_queue_update,
    )
    _download(result["video"]["url"], dest)
    print(f"Saved {dest}")


def generate_voice(dest: Path) -> None:
    print("\n=== Generating Spanish voice-over ===")
    result = fal_client.subscribe(
        TTS_MODEL,
        arguments={
            "text": SPEECH,
            "voice_setting": {
                "voice_id": "Friendly_Person",
                "speed": 1.0,
                "vol": 1.0,
                "pitch": 0,
                "emotion": "happy",
            },
            "language_boost": "Spanish",
            "output_format": "url",
        },
        with_logs=True,
        on_queue_update=on_queue_update,
    )
    _download(result["audio"]["url"], dest)
    print(f"Saved {dest}")


def _probe_duration(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(out.stdout.strip())


def mux(video: Path, audio: Path, dest: Path) -> None:
    print("\n=== Muxing voice onto clip ===")
    # Play the clip while Vorty speaks, then FREEZE the last frame for
    # SILENT_TAIL_SECONDS with silent audio: the agent holds still and quiet at
    # the end. The video is trimmed to the speech length, its final frame is
    # cloned for the tail (tpad), and the audio is padded with silence (apad).
    audio_dur = _probe_duration(audio)
    tail = SILENT_TAIL_SECONDS
    total = audio_dur + tail
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(video),
            "-i", str(audio),
            "-filter_complex",
            (
                f"[0:v]trim=0:{audio_dur:.3f},setpts=PTS-STARTPTS,"
                f"tpad=stop_mode=clone:stop_duration={tail}[v];"
                f"[1:a]apad=pad_dur={tail}[a]"
            ),
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-t", f"{total:.3f}", str(dest),
        ],
        check=True,
    )
    print(f"Saved {dest}")


def revoice(src_video: Path, audio: Path, dest: Path) -> None:
    print("\n=== Swapping in the new voice ===")
    # Reuse an existing clip's video (kept as-is, including its frozen silent
    # tail) and replace only the audio with the freshly generated voice, padded
    # with silence to the clip's length so the ending stays quiet.
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(src_video),
            "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-af", "apad", "-shortest", str(dest),
        ],
        check=True,
    )
    print(f"Saved {dest}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--aspect-ratio",
        default="16:9",
        choices=["16:9", "9:16", "1:1"],
        help="Output frame shape (default: 16:9).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Where to save the .mp4 (default: {DEFAULT_OUT_DIR}).",
    )
    parser.add_argument(
        "--keep-parts",
        action="store_true",
        help="Keep the intermediate silent clip and the voice-over file.",
    )
    parser.add_argument(
        "--revoice",
        type=Path,
        default=None,
        help="Reuse this existing clip's video and only regenerate the voice "
        "(skips image upload and the video model).",
    )
    args = parser.parse_args()

    if not os.environ.get("FAL_KEY"):
        sys.exit("FAL_KEY is not set. Get one from fal.ai and `export FAL_KEY=...` first.")
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg is not on PATH. Install it (e.g. `brew install ffmpeg`) first.")

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    silent = out_dir / "intro_v4_silent.mp4"
    voice = out_dir / "intro_v4_voice.mp3"
    final = out_dir / "intro_v4.mp4"

    # Never overwrite a previous render in place: keep a timestamped backup so a
    # good clip is never lost to a re-run.
    if final.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = out_dir / f"intro_v4_backup_{stamp}.mp4"
        shutil.copy2(final, backup)
        print(f"Backed up existing clip -> {backup}")

    if args.revoice is not None:
        src_video = args.revoice
        if not src_video.exists():
            sys.exit(f"--revoice source not found: {src_video}")
        generate_voice(voice)
        revoice(src_video, voice, final)
        if not args.keep_parts:
            voice.unlink(missing_ok=True)
        print(f"\nDone -> {final}")
        return

    image_urls = upload_reference_images()
    generate_video(image_urls, silent, args.aspect_ratio)
    generate_voice(voice)
    mux(silent, voice, final)

    if not args.keep_parts:
        silent.unlink(missing_ok=True)
        voice.unlink(missing_ok=True)
    print(f"\nDone -> {final}")


if __name__ == "__main__":
    main()
