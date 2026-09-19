"""Animate vorty-face-no-headphones.svg with each accessory, via QuiverAI.

For every accessory SVG in vortex/wall/media/accessories/, layers it onto the
bare face (same viewBox on both, so no offset math), then sends the combined
SVG straight to QuiverAI's /v1/svgs/animations (no vectorization needed, the
input is already vector). Every call uses the exact same motion prompt so the
whole set reads as one animated family instead of ten different styles.
Needs QUIVERAI_API_KEY in the environment (see .env.example).

Usage:
    python scripts/quiver_accessory_animations.py [-o output_dir] [accessory ...]

With no accessory names given, animates all of them. Pass one or more
filenames (e.g. "halo.svg") to animate a subset.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from quiver_animate import animate  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEDIA_DIR = os.path.join(REPO_ROOT, "vortex", "wall", "media")
ACCESSORY_DIR = os.path.join(MEDIA_DIR, "accessories")
BASE_FACE = os.path.join(MEDIA_DIR, "vorty-face-no-headphones.svg")
DEFAULT_OUTPUT_DIR = os.path.join(ACCESSORY_DIR, "animated")

# One prompt for every accessory on purpose: consistency across the set
# matters more than a bespoke description per item. The model can see the
# actual accessory shape in the SVG it receives, so it still tailors the
# accent motion to what's there.
PROMPT = (
    "Subtle, elegant looping idle animation for a small rounded robot mascot "
    "head icon. Calm and refined, never cartoonish or fast: a slow ~2 second "
    "seamless loop. The head does a barely-perceptible soft breathing scale, "
    "a couple of percent at most. The one accessory attached to the head gets "
    "a single tasteful accent motion that fits its shape - a gentle bob, sway, "
    "or soft glow pulse - eased with the exact same slow, smooth timing as the "
    "head's breathing, so head and accessory read as one unified, elegant "
    "motion. No spins, no shakes, no hard cuts, no bright flashes."
)


def compose(base_svg: str, accessory_svg: str) -> str:
    accessory_inner = accessory_svg.split(">", 1)[1].rsplit("</svg>", 1)[0]
    return base_svg.rsplit("</svg>", 1)[0] + accessory_inner + "</svg>"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "accessories",
        nargs="*",
        help="accessory filenames to animate (default: all .svg files in accessories/)",
    )
    parser.add_argument("-o", "--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    api_key = os.environ.get("QUIVERAI_API_KEY")
    if not api_key:
        sys.exit("QUIVERAI_API_KEY is not set (add it to .env)")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    if args.accessories:
        names = args.accessories
    else:
        names = sorted(f for f in os.listdir(ACCESSORY_DIR) if f.endswith(".svg"))

    with open(BASE_FACE) as f:
        base_svg = f.read()

    os.makedirs(args.output_dir, exist_ok=True)

    results = {}
    for name in names:
        acc_path = os.path.join(ACCESSORY_DIR, name)
        with open(acc_path) as f:
            accessory_svg = f.read()
        combined = compose(base_svg, accessory_svg)

        print(f"Animating {name}...")
        try:
            animated_svg = animate(combined, PROMPT, headers)
        except Exception as e:  # noqa: BLE001
            print(f"  FAILED: {e}")
            results[name] = f"failed: {e}"
            continue

        out_path = os.path.join(args.output_dir, name)
        with open(out_path, "w") as f:
            f.write(animated_svg)
        print(f"  saved {out_path}")
        results[name] = "ok"

    print("\nSummary:")
    for name, status in results.items():
        print(f"  {name}: {status}")


if __name__ == "__main__":
    main()
