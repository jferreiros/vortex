"""Render a text-free page-intro clip via fal-ai/kling-video/o1/reference-to-video.

Same as generate_intro_v2.py, but the background is explicitly pure solid
white (#FFFFFF) instead of pale grey, for compositing onto a white page.

Both stills of the "Vorty" character in vortex/wall/media/reference/ are
uploaded once and referenced as @Image1 / @Image2 for a consistent design.

Requires:
    uv run --with fal-client python scripts/video/generate_intro_v3.py
    export FAL_KEY=...   # from fal.ai dashboard - never commit it

Usage:
    uv run --with fal-client python scripts/video/generate_intro_v3.py
    uv run --with fal-client python scripts/video/generate_intro_v3.py --aspect-ratio 9:16
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import fal_client
import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REFERENCE_DIR = REPO_ROOT / "vortex" / "wall" / "media" / "reference"
DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "output"

# Order matters: first upload becomes @Image1, second becomes @Image2.
IMAGE_FILES = ["avatar2d.png", "Unknown.jpg"]

MODEL = "fal-ai/kling-video/o1/reference-to-video"

PROMPT = (
    "Continuous single wide tracking shot, static camera. Background: "
    "pure solid flat white, hex FFFFFF, no gradient, no grey tint, no "
    "shadows on the background, infinite white studio cyclorama, stays "
    "pure white FFFFFF for the whole clip. Soft cinematic lighting, "
    "35mm lens, one continuous shot, no on-screen text, no UI overlays, "
    "no captions, no icons, no readable words anywhere. Keep the "
    "character's design matching @Image1 and @Image2: a small round "
    "white robot receptionist named Vorty, glossy plastic, black "
    "rounded visor face, green headset with boom mic, black blazer, "
    "grey clipboard. Order, strictly one part after another, never "
    "overlapping: (1) Vorty enters walking in from the far left edge, "
    "confident bounce, stops centered, alone. (2) Once Vorty is still "
    "and alone, several classic phone handset receivers materialize "
    "floating around it; two translucent, lighter-opacity ghost-like "
    "clones of Vorty fade in, one on each side, and pick up and handle "
    "the phones, talking and gesturing, clearly showing many calls "
    "handled at once. (3) The ghost clones and phones fade and merge "
    "smoothly back into the single main Vorty, exactly as before. (4) "
    "Only once Vorty is single again, a large messy stack of loose "
    "paper sheets materializes in its hands out of nowhere; Vorty flips "
    "through them at high speed, sorting, and briskly files each sheet "
    "into folders and a small open filing cabinet drawer beside it, "
    "which fills with neatly squared stacks in seconds; once done, the "
    "folders and cabinet vanish completely, leaving Vorty alone with "
    "just its clipboard. (5) Vorty gives a small satisfied nod, tucks "
    "the clipboard under one arm, and walks off, exiting at the far "
    "right edge. Smooth continuous physical motion throughout, no "
    "captions, no readable text, no speech bubbles, no letter- or "
    "number-like symbols."
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


def generate(image_urls: list[str], out_dir: Path, aspect_ratio: str) -> None:
    print("\n=== Generating intro v3 ===")
    result = fal_client.subscribe(
        MODEL,
        arguments={
            "prompt": PROMPT,
            "image_urls": image_urls,
            "duration": "10",
            "aspect_ratio": aspect_ratio,
        },
        with_logs=True,
        on_queue_update=on_queue_update,
    )
    video_url = result["video"]["url"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "intro_v3.mp4"
    with httpx.stream("GET", video_url, follow_redirects=True) as response:
        response.raise_for_status()
        with open(out_path, "wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)
    print(f"Saved {out_path} ({video_url})")


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
    args = parser.parse_args()

    if not os.environ.get("FAL_KEY"):
        sys.exit("FAL_KEY is not set. Get one from fal.ai and `export FAL_KEY=...` first.")

    image_urls = upload_reference_images()
    generate(image_urls, args.out_dir, args.aspect_ratio)


if __name__ == "__main__":
    main()
