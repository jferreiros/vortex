"""Render the talking page-intro clip with ONE model that makes picture and
voice together: fal-ai/veo3.1/fast/image-to-video (Google Veo 3.1) generates
the video and its English speech in a single pass, no separate TTS.

Pipeline, one command:
  1. Pad Vorty's square avatar onto a white 16:9 (or 9:16) canvas so the
     character is not cropped by Veo.
  2. Veo animates it on pure white and speaks the English line natively.
  3. ffmpeg holds the last frame and pads silence for 2 extra seconds, so the
     clip ends with a guaranteed silent tail (the speech is baked into the
     model's audio track, so the tail is added afterwards).

Requires ffmpeg on PATH and:
    export FAL_KEY=...   # from fal.ai dashboard - never commit it

Usage:
    uv run --with fal-client python scripts/video/generate_intro_v5.py
    uv run --with fal-client python scripts/video/generate_intro_v5.py --aspect-ratio 9:16
    uv run --with fal-client python scripts/video/generate_intro_v5.py --keep-parts
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

# Single still that seeds the character; padded to 16:9/9:16 before upload.
IMAGE_FILE = "avatar2d.png"

# One model, picture + voice together.
VIDEO_MODEL = "fal-ai/veo3.1/fast/image-to-video"

# Seconds to hold the clip on screen after the speech ends (silent tail).
SILENT_TAIL_SECONDS = 2.0

# The line Vorty says, delivered natively by Veo, per language. Kept as the
# single source of truth.
SPEECH = {
    "en": (
        "Hi, I'm Vorty! A voice agent built by the Vortex team at HackSpain "
        "that schedules appointments for medical clinics."
    ),
    "es": (
        "¡Hola, soy Vorty! Un agente de voz creado por el equipo Vortex en "
        "HackSpain que gestiona citas para clínicas médicas."
    ),
}

LANG_NAME = {"en": "clear friendly English", "es": "clear friendly Spanish"}


def build_prompt(lang: str) -> str:
    # The prompt tells Veo to finish the sentence and then stay quiet so the
    # silent tail we add afterwards reads naturally.
    return (
        "A small round white robot receptionist named Vorty on a pure solid "
        "flat white background, hex FFFFFF, no gradient, no shadows, infinite "
        "white studio cyclorama, soft cinematic lighting, static camera, one "
        "continuous shot. Vorty is glossy white plastic with a black rounded "
        "visor face and no mouth, a green headset with a boom mic, a black "
        "blazer and a grey clipboard. Vorty faces the camera and introduces "
        "itself warmly and cheerfully with lively, varied hand gestures — a "
        "quick wave hello, open presenting hands, a small friendly thumbs up, "
        f"gentle head nods — while keeping eye contact. It speaks in {LANG_NAME[lang]}.\n"
        "Sample Dialogue:\n"
        f'Vorty: "{SPEECH[lang]}"\n'
        "After finishing the line, Vorty stops talking and stands calmly "
        "smiling, gesturing softly and silently for the rest of the clip. No "
        "other voices, no background music, no on-screen text, no captions, no "
        "subtitles, no readable words or letters anywhere."
    )


def on_queue_update(update: object) -> None:
    if isinstance(update, fal_client.InProgress):
        for log in update.logs:
            print(log["message"])


def _download(url: str, dest: Path) -> None:
    with httpx.stream("GET", url, follow_redirects=True) as response:
        response.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)


def prepare_image(dest: Path, aspect_ratio: str, src: Path) -> None:
    """Pad the reference still onto a white 16:9/9:16 canvas so Veo does not
    crop the character away when it fits the frame."""
    if not src.exists():
        raise FileNotFoundError(f"Missing reference image: {src}")
    if aspect_ratio == "9:16":
        canvas, scale = "1080:1920", "scale=1080:-1"
    else:  # 16:9
        canvas, scale = "1920:1080", "scale=-1:1080"
    print(f"Preparing {aspect_ratio} white canvas from {src.name}...")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(src),
            "-vf", f"{scale},pad={canvas}:(ow-iw)/2:(oh-ih)/2:white",
            str(dest),
        ],
        check=True,
        capture_output=True,
    )


def generate_video(image_url: str, dest: Path, aspect_ratio: str, lang: str) -> None:
    print(f"\n=== Generating clip with native voice (Veo 3.1, {lang}) ===")
    result = fal_client.subscribe(
        VIDEO_MODEL,
        arguments={
            "prompt": build_prompt(lang),
            "image_url": image_url,
            "aspect_ratio": aspect_ratio,
            "duration": "8s",
            "resolution": "720p",
            "generate_audio": True,
        },
        with_logs=True,
        on_queue_update=on_queue_update,
    )
    _download(result["video"]["url"], dest)
    print(f"Saved {dest}")


def add_silent_tail(video: Path, dest: Path) -> None:
    print("\n=== Adding silent tail ===")
    # Hold the last frame and pad silence for SILENT_TAIL_SECONDS so the clip
    # ends with no speech. The model's audio is baked into the video, so this
    # runs afterwards; video and audio are re-encoded to extend cleanly.
    sec = SILENT_TAIL_SECONDS
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video),
            "-vf", f"tpad=stop_mode=clone:stop_duration={sec}",
            "-af", f"apad=pad_dur={sec}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            str(dest),
        ],
        check=True,
    )
    print(f"Saved {dest}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--aspect-ratio",
        default="16:9",
        choices=["16:9", "9:16"],
        help="Output frame shape (default: 16:9). Veo only supports 16:9/9:16.",
    )
    parser.add_argument(
        "--lang",
        default="en",
        choices=["en", "es"],
        help="Language Vorty speaks (default: en).",
    )
    parser.add_argument(
        "--image",
        type=Path,
        default=REFERENCE_DIR / IMAGE_FILE,
        help=f"Reference still to seed the character (default: {IMAGE_FILE}).",
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
        help="Keep the intermediate padded still and the raw talking clip.",
    )
    args = parser.parse_args()

    if not os.environ.get("FAL_KEY"):
        sys.exit("FAL_KEY is not set. Get one from fal.ai and `export FAL_KEY=...` first.")
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg is not on PATH. Install it (e.g. `brew install ffmpeg`) first.")

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    seed = out_dir / "intro_v5_seed.png"
    talking = out_dir / "intro_v5_talking.mp4"
    final = out_dir / "intro_v5.mp4"

    # Never overwrite a previous render in place: keep a timestamped backup so a
    # good clip is never lost to a re-run.
    if final.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = out_dir / f"intro_v5_backup_{stamp}.mp4"
        shutil.copy2(final, backup)
        print(f"Backed up existing clip -> {backup}")

    prepare_image(seed, args.aspect_ratio, args.image)
    print(f"Uploading {seed.name}...")
    image_url = fal_client.upload_file(str(seed))
    generate_video(image_url, talking, args.aspect_ratio, args.lang)
    add_silent_tail(talking, final)

    if not args.keep_parts:
        seed.unlink(missing_ok=True)
        talking.unlink(missing_ok=True)
    print(f"\nDone -> {final}")


if __name__ == "__main__":
    main()
