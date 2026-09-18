"""Refresh ``cases/public-cases.json`` from the dashboard.

    uv run python -m evals.corpus.fetch            # refresh in place
    uv run python -m evals.corpus.fetch --check    # fail if it has changed

Run it each morning of the event. The roster itself is fixed — the same seed
builds it for every process — but the slot in a booking answer is anchored to
09:00 Europe/Madrid on the day it is dialled, so a booking answer changes
overnight. A stale roster judges yesterday's call correctly and today's wrong.

The URL carries a content hash and therefore changes whenever the organisers
publish a correction. ``--discover`` re-reads the Problems page to find the
current one instead of trusting the constant below.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

from evals.corpus.catalogue import CASES_FILE

DOCS_PAGE = "https://hackspain.getprosperapp.com/leaderboard/docs/problems"
ASSET_URL = "https://hackspain.getprosperapp.com/leaderboard/assets/public-cases-BH3bsRyz.json"
INDEX_URL = "https://hackspain.getprosperapp.com/leaderboard/"


def discover_url(timeout: float = 20.0) -> str:
    """Find the current ``public-cases-*.json`` asset from the site's bundle.

    The docs render client-side, so the link is in the JavaScript bundle rather
    than in the HTML. Falls back to the pinned URL when nothing is found, and
    says which it used.
    """
    with urllib.request.urlopen(INDEX_URL, timeout=timeout) as response:  # noqa: S310
        html = response.read().decode("utf-8", "replace")
    bundles = re.findall(r'src="([^"]+\.js)"', html)
    for bundle in bundles:
        url = bundle
        if not bundle.startswith("http"):
            url = INDEX_URL.rstrip("/") + "/" + bundle.lstrip("/")
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
                source = response.read().decode("utf-8", "replace")
        except OSError:
            continue
        found = re.search(r'["\']([^"\']*public-cases-[^"\']+\.json)["\']', source)
        if found:
            path = found.group(1)
            return path if path.startswith("http") else INDEX_URL.rstrip("/") + path
    return ASSET_URL


def download(url: str, timeout: float = 30.0) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
        return response.read()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.corpus.fetch", description=__doc__)
    parser.add_argument("--url", default=None, help="override the asset URL")
    parser.add_argument("--discover", action="store_true", help="find the URL from the site bundle")
    parser.add_argument("--check", action="store_true", help="do not write; exit 1 if it changed")
    parser.add_argument("--out", type=Path, default=CASES_FILE)
    args = parser.parse_args(argv)

    url = args.url or (discover_url() if args.discover else ASSET_URL)
    print(f"fetching {url}")
    try:
        blob = download(url)
    except OSError as error:
        print(f"could not fetch the roster: {error}", file=sys.stderr)
        return 2

    try:
        doc = json.loads(blob)
        count = len(doc["cases"])
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        print(f"the download is not a case roster: {error}", file=sys.stderr)
        return 2

    new = hashlib.sha256(blob).hexdigest()
    old = hashlib.sha256(args.out.read_bytes()).hexdigest() if args.out.exists() else ""
    print(f"{count} cases · sha256 {new[:12]}")

    if new == old:
        print("unchanged")
        return 0
    if args.check:
        print(f"CHANGED: on disk {old[:12] or '(absent)'}, upstream {new[:12]}", file=sys.stderr)
        print("run without --check to update, then re-read the problem pages", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(blob)
    print(f"wrote {args.out} (was {old[:12] or 'absent'})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
