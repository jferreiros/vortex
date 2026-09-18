.PHONY: install run smoke test call tunnel tail lint fmt board

PORT ?= 7860
BOARD_PORT ?= 8080
N ?= 1

install:
	uv sync --all-groups

run:
	uv run python -m vortex

board:
	uv run python -m vortex.observability.live

dev:
	uv run uvicorn vortex.line.server:app --host 0.0.0.0 --port $(PORT) --reload

smoke:
	uv run pytest tests/test_smoke.py -q

test:
	uv run pytest -q

call:
	uv run python scripts/fake_caller.py --url ws://localhost:$(PORT)/ws --calls $(N)

tunnel:
	ngrok http $(PORT)

tail:
	tail -f logs/calls.jsonl

lint:
	uv run ruff check .

fmt:
	uv run ruff format . && uv run ruff check --fix .
