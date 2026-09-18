"""``python -m vortex`` starts the server."""

from __future__ import annotations

import logging

import uvicorn

from vortex.settings import get_settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    settings = get_settings()
    logging.getLogger("vortex").info("modes: %s", settings.describe())
    uvicorn.run("vortex.line.server:app", host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
