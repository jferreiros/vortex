"""Improve the workflow-shape icons with QuiverAI's SVG edit endpoint.

Unlike vectorizations/animations (the only two endpoints this repo had
wired before), /v1/svgs/edits takes an existing SVG plus a text prompt and
returns a revised SVG - a real "edit this design" call, not a from-scratch
generation. Each of the 4 workflow shapes gets its own prompt describing
what's wrong/missing on top of one shared style prompt (single solid fill,
transparent background, maxed to fill the square canvas without clipping).

Never overwrites the hand-drawn originals: results are written next to them
with a "-quiver" suffix so both versions can be compared.

Needs QUIVERAI_API_KEY in the environment (see .env.example).

Usage:
    python scripts/quiver_shape_edits.py [shape ...]

With no shape names given, edits all 4. Pass one or more of
call-outgoing, call-incoming, message, visit to edit a subset.
"""

import argparse
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(__file__))
from quiver_animate import _first_svg  # noqa: E402

API_BASE = "https://api.quiver.ai/v1"
REQUEST_TIMEOUT_SECS = 280

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEDIA_DIR = os.path.join(
    REPO_ROOT, "vortex", "wall", "src", "pages", "clinic", "workflows", "media"
)

STYLE_PROMPT = (
    "Keep the central shape as a single solid fill in color #2f7d5c - no "
    "stroke outlines, no separate background rectangle, background stays "
    "fully transparent. It sits on a square canvas: make it as big as "
    "possible while still fitting entirely inside that square, with no "
    "part of it cut off by the canvas edge."
)

SHAPE_PROMPTS = {
    "call-outgoing": (
        "Make this clearly look like a telephone - an old handset/desk "
        "phone silhouette, instantly recognizable as a phone. Keep the "
        "solid arrow pointing away from the phone (up and to the right, "
        "exiting the frame) to show an outgoing call. "
    )
    + STYLE_PROMPT,
    "call-incoming": (
        "Make this clearly look like a telephone - an old handset/desk "
        "phone silhouette, instantly recognizable as a phone. Keep the "
        "solid arrow pointing INTO the phone (arriving from the top right, "
        "arrowhead landing on the phone) to show an incoming call. "
    )
    + STYLE_PROMPT,
    "message": (
        "Make this clearly look like a message bubble - a rounded chat "
        "speech bubble with a small pointed tail at the bottom. "
    )
    + STYLE_PROMPT,
    "visit": (
        "Make this clearly look like a hospital silhouette - a simple "
        "hospital building shape. The letter H must be cut out of the "
        "building as a real transparent hole (not drawn on top of the "
        "fill), the way a hospital sign shows an H. "
    )
    + STYLE_PROMPT,
}


def edit(svg: str, prompt: str, headers: dict) -> str:
    resp = requests.post(
        f"{API_BASE}/svgs/edits",
        headers=headers,
        json={
            "model": "arrow-2",
            "prompt": prompt,
            "stream": False,
            "max_review_steps": 2,
            "reasoning_effort": "medium",
            "settings": {
                "max_output_tokens": 4096,
                "orchestrator_max_output_tokens": 4096,
                "shallow_max_output_tokens": 2048,
                "temperature": 0.4,
            },
            "svg": svg,
            "svg_source": None,
        },
        timeout=REQUEST_TIMEOUT_SECS,
    )
    resp.raise_for_status()
    return _first_svg(resp.json())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "shapes", nargs="*", choices=list(SHAPE_PROMPTS) or None, help="subset to edit"
    )
    args = parser.parse_args()

    api_key = os.environ.get("QUIVERAI_API_KEY")
    if not api_key:
        sys.exit("QUIVERAI_API_KEY is not set (add it to .env)")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    names = args.shapes or list(SHAPE_PROMPTS)

    results = {}
    for name in names:
        src_path = os.path.join(MEDIA_DIR, f"{name}.svg")
        with open(src_path) as f:
            svg = f.read()

        print(f"Editing {name}...")
        try:
            edited_svg = edit(svg, SHAPE_PROMPTS[name], headers)
        except Exception as e:  # noqa: BLE001
            print(f"  FAILED: {e}")
            results[name] = f"failed: {e}"
            continue

        out_path = os.path.join(MEDIA_DIR, f"{name}-quiver.svg")
        with open(out_path, "w") as f:
            f.write(edited_svg)
        print(f"  saved {out_path}")
        results[name] = "ok"

    print("\nSummary:")
    for name, status in results.items():
        print(f"  {name}: {status}")


if __name__ == "__main__":
    main()
