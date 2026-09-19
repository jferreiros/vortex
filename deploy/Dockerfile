# syntax=docker/dockerfile:1.7
#
# Vortex — the WebSocket the platform dials.
#
# Two stages so a dependency install is cached across the many rebuilds a
# hackathon weekend produces. Build from the repository root:
#
#     docker compose -f deploy/compose.yaml build
#
# The image carries no key. Every secret arrives as an environment variable at
# run time (see deploy/.env.example). Nothing is copied wholesale into the
# image either: each COPY names its path, so a stray .env can never ride along.

# ---------------------------------------------------------------- build stage
FROM python:3.12-slim-bookworm AS builder

# Pinned to the uv that wrote uv.lock: the lock is revision 3, which older uv
# cannot read. The `*-bookworm-slim` variants stop before 0.12, so this is the
# plain image, a static musl binary at /uv that runs fine on debian.
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv

# UV_PYTHON_DOWNLOADS=never keeps uv on the interpreter this image already has.
# The repository's .python-version pins 3.14 for laptops; pyproject only asks
# for >=3.12, and 3.12 is the version every locked wheel publishes today.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first, without the project: this layer only changes when
# uv.lock or pyproject.toml change, so day-to-day code pushes rebuild in seconds.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --locked --no-dev --no-install-project

COPY pyproject.toml uv.lock README.md ./
COPY vortex ./vortex
COPY scripts ./scripts
COPY database ./database

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# -------------------------------------------------------------- runtime stage
FROM python:3.12-slim-bookworm

# libgomp1: onnxruntime's OpenMP runtime. libsndfile1: soundfile's decoder on
# the platforms where the wheel does not bundle its own copy.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --system --create-home --uid 10001 vortex

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VORTEX_HOST=0.0.0.0 \
    VORTEX_PORT=7860 \
    VORTEX_WS_PATH=/ws \
    VORTEX_CALLS_LOG=/app/logs/calls.jsonl \
    VORTEX_PRODUCT_DB=/app/logs/vortex_product.db

WORKDIR /app
COPY --from=builder --chown=vortex:vortex /app /app
RUN mkdir -p /app/logs && chown vortex:vortex /app/logs

USER vortex
EXPOSE 7860

# The application already answers GET /health with its active modes. Probe it
# with the interpreter we ship rather than adding curl to the image.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7860/health', timeout=4).status == 200 else 1)"]

# Same entry point as `make run`.
CMD ["python", "-m", "vortex"]
