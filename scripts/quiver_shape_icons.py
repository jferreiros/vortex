"""Draw the 4 workflow-shape icons and vectorize them with QuiverAI.

QuiverAI has no text-to-SVG endpoint, only /v1/svgs/vectorizations
(raster -> SVG) and /v1/svgs/animations (SVG -> animated SVG). So this
script draws each icon as a bold, transparent-background raster (Pillow,
supersampled for clean anti-aliased edges) on a square canvas, then sends
it through QuiverAI's vectorizer to get the final SVG. These replace the
plain circle/parallelogram/square shapes in the workflow canvas, so every
icon is drawn chunky on purpose: the workflow node still centers a text
glyph on top of it, and a thin line-art icon would leave nothing solid
for that glyph to sit on.

Needs QUIVERAI_API_KEY in the environment (see .env.example).

Usage:
    python scripts/quiver_shape_icons.py [-o output_dir] [shape ...]

With no shape names given, generates all 4. Pass one or more of
call-outgoing, call-incoming, message, visit to generate a subset.
"""

import argparse
import math
import os
import sys
import tempfile

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(__file__))
from quiver_animate import vectorize  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUTPUT_DIR = os.path.join(
    REPO_ROOT, "vortex", "wall", "src", "pages", "clinic", "workflows", "media"
)

SIZE = 512
SUPERSAMPLE = 4
CANVAS = SIZE * SUPERSAMPLE
FILL = (47, 125, 92, 255)  # --color-primary (#2f7d5c), opaque


def _new_canvas():
    img = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _finish(img):
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def _rounded_rect(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def _thick_line(draw, p1, p2, width, fill):
    draw.line([p1, p2], fill=fill, width=width)
    r = width / 2
    for x, y in (p1, p2):
        draw.ellipse([x - r, y - r, x + r, y + r], fill=fill)


def _arrow(draw, tail, head, width, head_len, head_width, fill):
    _thick_line(draw, tail, head, width, fill)
    dx, dy = head[0] - tail[0], head[1] - tail[1]
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    base_x, base_y = head[0] - ux * head_len, head[1] - uy * head_len
    left = (base_x + px * head_width / 2, base_y + py * head_width / 2)
    right = (base_x - px * head_width / 2, base_y - py * head_width / 2)
    draw.polygon([head, left, right], fill=fill)


def draw_phone(outgoing: bool) -> Image.Image:
    img, draw = _new_canvas()

    # Old desk telephone, not a thin wireframe handset: a solid base with a
    # big horizontal handset (bulbous ear/mouth pieces) resting on top,
    # joined by a short cradle connector, all bold enough to stay solid and
    # spacious at icon size.
    base_box = [0.16 * CANVAS, 0.56 * CANVAS, 0.84 * CANVAS, 0.84 * CANVAS]
    _rounded_rect(draw, base_box, radius=int(0.05 * CANVAS), fill=FILL)

    handset_y = 0.40 * CANVAS
    left = (0.28 * CANVAS, handset_y)
    right = (0.72 * CANVAS, handset_y)
    _thick_line(draw, left, right, width=int(0.16 * CANVAS), fill=FILL)
    bulb_r = 0.13 * CANVAS
    for cx, cy in (left, right):
        draw.ellipse([cx - bulb_r, cy - bulb_r, cx + bulb_r, cy + bulb_r], fill=FILL)

    connector_box = [
        0.5 * CANVAS - 0.05 * CANVAS,
        handset_y + bulb_r * 0.4,
        0.5 * CANVAS + 0.05 * CANVAS,
        base_box[1] + 0.02 * CANVAS,
    ]
    draw.rectangle(connector_box, fill=FILL)

    # Direction arrow off the right (earpiece) bulb: pointing away for an
    # outgoing call, pointing in toward the earpiece for an incoming one.
    outer = (0.97 * CANVAS, 0.10 * CANVAS)
    inner = (right[0] + bulb_r * 0.6, handset_y - bulb_r * 0.6)
    width = int(0.075 * CANVAS)
    head_len = 0.16 * CANVAS
    head_width = 0.16 * CANVAS
    if outgoing:
        _arrow(draw, inner, outer, width, head_len, head_width, FILL)
    else:
        _arrow(draw, outer, inner, width, head_len, head_width, FILL)

    return _finish(img)


def draw_message() -> Image.Image:
    img, draw = _new_canvas()

    bubble_box = [0.12 * CANVAS, 0.14 * CANVAS, 0.88 * CANVAS, 0.72 * CANVAS]
    _rounded_rect(draw, bubble_box, radius=int(0.16 * CANVAS), fill=FILL)

    tail = [
        (0.22 * CANVAS, 0.70 * CANVAS),
        (0.36 * CANVAS, 0.70 * CANVAS),
        (0.18 * CANVAS, 0.90 * CANVAS),
    ]
    draw.polygon(tail, fill=FILL)

    return _finish(img)


def draw_visit() -> Image.Image:
    # Built on a mask so the door can be cut clean out of the silhouette
    # instead of painted over it (painting would leave a seam / blend with
    # the fill color at the edges).
    mask = Image.new("L", (CANVAS, CANVAS), 0)
    mdraw = ImageDraw.Draw(mask)

    roof = [
        (0.50 * CANVAS, 0.14 * CANVAS),
        (0.20 * CANVAS, 0.32 * CANVAS),
        (0.80 * CANVAS, 0.32 * CANVAS),
    ]
    mdraw.polygon(roof, fill=255)

    body_box = [0.26 * CANVAS, 0.30 * CANVAS, 0.74 * CANVAS, 0.86 * CANVAS]
    mdraw.rounded_rectangle(body_box, radius=int(0.02 * CANVAS), fill=255)

    door_box = [0.44 * CANVAS, 0.66 * CANVAS, 0.56 * CANVAS, 0.86 * CANVAS]
    mdraw.rounded_rectangle(door_box, radius=int(0.015 * CANVAS), fill=0)

    solid = Image.new("RGBA", (CANVAS, CANVAS), FILL)
    transparent = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    img = Image.composite(solid, transparent, mask)

    return _finish(img)

    return _finish(img)


SHAPES = {
    "call-outgoing": lambda: draw_phone(outgoing=True),
    "call-incoming": lambda: draw_phone(outgoing=False),
    "message": draw_message,
    "visit": draw_visit,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "shapes", nargs="*", choices=list(SHAPES) or None, help="subset of shapes to generate"
    )
    parser.add_argument("-o", "--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    api_key = os.environ.get("QUIVERAI_API_KEY")
    if not api_key:
        sys.exit("QUIVERAI_API_KEY is not set (add it to .env)")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    names = args.shapes or list(SHAPES)
    os.makedirs(args.output_dir, exist_ok=True)

    results = {}
    with tempfile.TemporaryDirectory() as tmp_dir:
        for name in names:
            png_path = os.path.join(tmp_dir, f"{name}.png")
            SHAPES[name]().save(png_path)

            print(f"Vectorizing {name}...")
            try:
                svg = vectorize(png_path, headers)
            except Exception as e:  # noqa: BLE001
                print(f"  FAILED: {e}")
                results[name] = f"failed: {e}"
                continue

            out_path = os.path.join(args.output_dir, f"{name}.svg")
            with open(out_path, "w") as f:
                f.write(svg)
            print(f"  saved {out_path}")
            results[name] = "ok"

    print("\nSummary:")
    for name, status in results.items():
        print(f"  {name}: {status}")


if __name__ == "__main__":
    main()
