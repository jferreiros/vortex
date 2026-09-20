"""Render the Vori booking-flow promo as short clips via fal-ai/kling-video/o1/reference-to-video.

The storyboard (phone rings -> identity check -> calendar search -> booking
confirmed, ~27s) is longer than this model allows in one call (duration cap is
10s per generation), so it's split into three ~9-10s continuous-camera clips.
Both stills of the "Vorty" character in vortex/wall/media/reference/ are
uploaded once and referenced in every clip's prompt as @Image1 / @Image2 so
the character design stays consistent across clips.

Requires:
    uv run --with fal-client python scripts/video/generate_promo.py
    export FAL_KEY=...   # from fal.ai dashboard - never commit it

Usage:
    uv run --with fal-client python scripts/video/generate_promo.py
    uv run --with fal-client python scripts/video/generate_promo.py --clip 2
    uv run --with fal-client python scripts/video/generate_promo.py --out-dir /tmp/promo
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

VORTY = (
    "Keep the character's design, proportions, and color palette exactly "
    "matching @Image1 and @Image2: a small round white robot receptionist "
    "named Vorty, glossy plastic finish, black rounded visor face, green "
    "headset with a boom mic, black blazer with a 'Vorty' name badge, "
    "holding a grey clipboard, standing against a clean pale-grey studio "
    "background."
)

CLIPS = [
    {
        "name": "01_ring_to_identity",
        "duration": "10",
        "prompt": (
            f"Continuous single tracking shot. {VORTY} Open on a stylized "
            "phone-call icon ringing above Vorty's head; it dissolves into a "
            "glowing thread connecting a small caller silhouette to Vorty as "
            "Vorty wakes from an idle slouch into an alert standing pose. "
            "Small sound-wave arcs pulse beside Vorty's headset ear as "
            "animated caption text types out letter by letter beside the "
            "caller silhouette: \"Hi, this is Maria Lopez, I'd like to book "
            'an appointment with dermatology." A thin folder icon flips '
            "open behind Vorty for a beat as Vorty reaches one arm forward "
            "and down in a searching gesture, with a soft page-flip visual "
            "accent. Vorty's own speech bubble then appears asking for the "
            "caller's date of birth, sound waves flowing back out toward "
            "the caller. The folder card snaps into place, pins to the top "
            "corner of frame, and locks with a small checkmark stamp as "
            "Vorty's visor lights up into a happy confirmed expression, arms "
            "raised. Smooth continuous camera dolly-in throughout, soft "
            "cinematic studio lighting, 35mm lens, clean commercial "
            "product-explainer look, no text overlays besides the described "
            "caption bubbles."
        ),
    },
    {
        "name": "02_history_to_calendar_lock",
        "duration": "10",
        "prompt": (
            f"Continuous single tracking shot. {VORTY} The pinned identity "
            "card from a moment ago flips over in frame to reveal a short "
            "scrolling list of past visit entries; one name, 'Dr. Ruiz', "
            "gets circled by an animated highlight as Vorty's visor "
            "flattens into a thinking expression, small dots drifting "
            "upward beside its head. The circled name floats up beside "
            "Vorty as a speech bubble appears asking to confirm Dr. Ruiz as "
            "the usual dermatologist, and Vorty gives a small nod. The "
            "scene transitions into a calendar board unrolling beside Vorty "
            "for Dr. Ruiz's schedule; a glowing cursor sweeps forward "
            "across the days starting Thursday, individual time slots "
            "lighting up one by one in sequence until it locks with a "
            "chime on 'Thursday 10:30', Vorty's pose shifting from a "
            "reaching searching stance back to a happy confirmed pose. "
            "Smooth continuous camera dolly and slight orbit throughout, "
            "soft cinematic studio lighting, 35mm lens, clean commercial "
            "product-explainer look."
        ),
    },
    {
        "name": "03_confirm_and_book",
        "duration": "8",
        "prompt": (
            f"Continuous single tracking shot. {VORTY} Vorty's speech "
            "bubble appears showing a proposed appointment slot, then the "
            "caller's waveform pulses back a short confirmation. The "
            "pinned patient identity card and the locked calendar slot "
            "glide together and merge into a single ticket in front of "
            "Vorty, which gets hit by a satisfying stamp animation with an "
            "ink flourish, as Vorty's expression settles into its happy "
            "confirmed pose with arms up. The ticket settles and gently "
            "rotates to face camera as a final caption reads 'Appointment "
            "booked.' Smooth continuous camera push-in to a final centered "
            "hero shot of Vorty holding the stamped ticket, soft cinematic "
            "studio lighting, 35mm lens, clean commercial product-explainer "
            "look, warm satisfying finish."
        ),
    },
]


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


def generate_clip(clip: dict, image_urls: list[str], out_dir: Path) -> None:
    print(f"\n=== Generating {clip['name']} ===")
    result = fal_client.subscribe(
        MODEL,
        arguments={
            "prompt": clip["prompt"],
            "image_urls": image_urls,
            "duration": clip["duration"],
            "aspect_ratio": "16:9",
        },
        with_logs=True,
        on_queue_update=on_queue_update,
    )
    video_url = result["video"]["url"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{clip['name']}.mp4"
    with httpx.stream("GET", video_url, follow_redirects=True) as response:
        response.raise_for_status()
        with open(out_path, "wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)
    print(f"Saved {out_path} ({video_url})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clip",
        type=int,
        choices=range(1, len(CLIPS) + 1),
        help="Render only this clip (1-based). Default: render all three in order.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Where to save the .mp4 files (default: {DEFAULT_OUT_DIR}).",
    )
    args = parser.parse_args()

    if not os.environ.get("FAL_KEY"):
        sys.exit("FAL_KEY is not set. Get one from fal.ai and `export FAL_KEY=...` first.")

    image_urls = upload_reference_images()
    clips = CLIPS if args.clip is None else [CLIPS[args.clip - 1]]
    for clip in clips:
        generate_clip(clip, image_urls, args.out_dir)


if __name__ == "__main__":
    main()
