"""Vectorize a raster image and animate it with QuiverAI.

Two-step pipeline: POST the source image (base64, so no public hosting is
needed) to /v1/svgs/vectorizations, then POST the resulting SVG (base64) to
/v1/svgs/animations with a motion prompt. Needs QUIVERAI_API_KEY in the
environment (see .env.example). Response shape for both endpoints is
{"data": [{"svg": "...", "mime_type": "image/svg+xml"}], ...} per QuiverAI's
OpenAPI spec.

Usage:
    python scripts/quiver_animate.py <image_path_or_url> <prompt> [-o output.svg]

Example:
    python scripts/quiver_animate.py \\
        vortex/wall/media/avatar2d.png \\
        "Entrance animation for a large hero avatar on a landing page. Bring it
        to life with movement as it appears" \\
        -o animated_avatar.svg
"""

import argparse
import base64
import mimetypes
import os
import sys

import requests

API_BASE = "https://api.quiver.ai/v1"
REQUEST_TIMEOUT_SECS = 280


def _image_input(image_path_or_url: str) -> dict:
    if image_path_or_url.startswith(("http://", "https://")):
        return {"url": image_path_or_url}
    with open(image_path_or_url, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")
    mime_type = mimetypes.guess_type(image_path_or_url)[0] or "image/png"
    return {"base64": encoded, "mime_type": mime_type}


def _first_svg(response_json: dict) -> str:
    data = response_json.get("data") or []
    if not data or "svg" not in data[0]:
        raise RuntimeError(f"no svg in response: {response_json}")
    return data[0]["svg"]


def vectorize(image_path_or_url: str, headers: dict) -> str:
    resp = requests.post(
        f"{API_BASE}/svgs/vectorizations",
        headers=headers,
        json={"model": "arrow-1", "stream": False, "image": _image_input(image_path_or_url)},
        timeout=REQUEST_TIMEOUT_SECS,
    )
    resp.raise_for_status()
    return _first_svg(resp.json())


def animate(svg: str, prompt: str, headers: dict) -> str:
    encoded_svg = base64.b64encode(svg.encode("utf-8")).decode("utf-8")
    resp = requests.post(
        f"{API_BASE}/svgs/animations",
        headers=headers,
        json={
            "model": "arrow-2",
            "prompt": prompt,
            "stream": False,
            "svg_source": {"base64": encoded_svg},
        },
        timeout=REQUEST_TIMEOUT_SECS,
    )
    resp.raise_for_status()
    return _first_svg(resp.json())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image_path_or_url", help="local path or URL of the source raster image")
    parser.add_argument("prompt", help="Motion prompt for the animation step")
    parser.add_argument("-o", "--output", default="animated.svg", help="output SVG path")
    args = parser.parse_args()

    api_key = os.environ.get("QUIVERAI_API_KEY")
    if not api_key:
        sys.exit("QUIVERAI_API_KEY is not set (add it to .env)")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    print("Vectorizing image...")
    vector_svg = vectorize(args.image_path_or_url, headers)

    print("Animating SVG...")
    final_svg = animate(vector_svg, args.prompt, headers)

    with open(args.output, "w") as f:
        f.write(final_svg)
    print(f"Success! Saved as {args.output}")


if __name__ == "__main__":
    main()
