"""Render a text-free page-intro clip via fal-ai/kling-video/o1/reference-to-video.

One continuous ~10s shot: Vorty walks in from the left, cycles through its
functions (handling many calls at once, flipping through physical folders,
scanning a schedule board), then walks off to the right. No on-screen text,
captions or speech bubbles anywhere in the prompt - the target platform can't
render text reliably.

Both stills of the "Vorty" character in vortex/wall/media/reference/ are
uploaded once and referenced as @Image1 / @Image2 for a consistent design.

Requires:
    uv run --with fal-client python scripts/video/generate_intro.py
    export FAL_KEY=...   # from fal.ai dashboard - never commit it

Usage:
    uv run --with fal-client python scripts/video/generate_intro.py
    uv run --with fal-client python scripts/video/generate_intro.py --aspect-ratio 9:16
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
    "Continuous single wide tracking shot, static camera, clean plain "
    "pale-grey studio background, soft cinematic lighting, 35mm lens, "
    "seamless one-shot motion, no on-screen text, no UI overlays, no "
    "captions, no icons, no readable words anywhere in frame. Keep the "
    "character's design, proportions, and color palette exactly matching "
    "@Image1 and @Image2: a small round white robot receptionist named "
    "Vorty, glossy plastic finish, black rounded visor face, green "
    "headset with a boom mic, black blazer, holding a grey clipboard. "
    "Vorty enters the frame walking in from the far left edge with a "
    "confident bounce, and comes to a stop centered in frame. This "
    "happens first, on its own, before anything else starts. Next, and "
    "only once Vorty is standing still, Vorty clones itself: it splits "
    "into several identical copies of itself that fan out to its sides, "
    "each copy holding a classic phone handset receiver up to its "
    "headset, all talking and gesturing at the same time, clearly "
    "showing Vorty handling many phone calls at once. After a moment, "
    "all of the cloned copies walk back together and merge smoothly "
    "back into one single Vorty, exactly as it looked before it cloned "
    "itself. Only once Vorty is a single figure again, and the calls "
    "sequence is fully finished, a large messy loose stack of paper "
    "sheets materializes and appears in Vorty's hands out of nowhere. "
    "Vorty flips through the papers at high speed with both hands, "
    "sorting them as it goes, and briskly files each sheet into a set "
    "of folders and a small open filing cabinet drawer beside it, the "
    "drawer filling up with neatly squared, perfectly ordered stacks in "
    "seconds. Once every sheet is filed, the folders and the filing "
    "cabinet vanish and disappear completely, leaving Vorty standing "
    "alone with just its clipboard again. Vorty gives a small satisfied "
    "nod, tucks the clipboard under one arm, and walks off, exiting the "
    "frame at the far right edge. These four parts happen strictly one "
    "after another, never overlapping or at the same time: first enter, "
    "then clone into many for the calls, then merge back into one, then "
    "the papers appear and get filed and vanish, then exit. Smooth "
    "continuous physical motion throughout, no captions, no readable "
    "text, no speech bubbles, no symbols that resemble letters or "
    "numbers."
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
    print("\n=== Generating intro ===")
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
    out_path = out_dir / "intro.mp4"
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
