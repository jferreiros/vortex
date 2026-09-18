.PHONY: install run smoke test call try-api tunnel tail lint fmt board evals evals-logic evals-conversation evals-voice evals-report evals-accept evals-selftest evals-discord

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

try-api:
	uv run python scripts/api/try_api.py

tunnel:
	ngrok http $(PORT)

tail:
	tail -f logs/calls.jsonl

lint:
	uv run ruff check .

fmt:
	uv run ruff format . && uv run ruff check --fix .

# ---- evals (see docs/evals.md) ---------------------------------------------
.PHONY: evals evals-logic evals-conversation evals-voice evals-report evals-accept evals-selftest evals-discord

evals:            ## layers 1 + 2 + 4, no keys needed; the CI entry point (exit 1 on failure)
	uv run python -m evals ci

evals-logic:      ## layer 1 only: tool cases, seconds
	uv run python -m evals logic

evals-conversation: ## layer 2 only: scripted callers; BRAIN=rules|openai|replay|auto, K=repeats, RECORD=1
	uv run python -m evals conversation --brain $(or $(BRAIN),auto) --repeat $(or $(K),1) $(if $(RECORD),--record,)

evals-voice:      ## layer 3: provider benchmark. Fake unless REAL=1; MAX_EUR caps a real run
	uv run python -m evals voice $(if $(REAL),--real,) --max-eur $(or $(MAX_EUR),0.50) $(if $(STACKS),--stacks $(STACKS),)

evals-corpus:     ## layer 4: the organisers' 73 published cases and the surface behind them
	uv run python -m evals corpus $(if $(ONLY),--only $(ONLY),) $(if $(LOG),--judge-log $(LOG),)

evals-coverage:   ## where the 196 points are, and what the public cases never show
	uv run python -m evals corpus --coverage

evals-verify:     ## do the published answers exist in the API we snapshotted?
	uv run python -m evals corpus --verify-roster --only world

evals-fetch:      ## refresh evals/corpus/cases/public-cases.json (run it each morning)
	uv run python -m evals.corpus.fetch

evals-snapshot:   ## freeze the real clinic for offline judging; needs PLATFORM_API_KEY
	uv run python -m evals.corpus.snapshot

evals-report:     ## rebuild evals/results/summary.md and report.html
	uv run python -m evals report

evals-accept:     ## promote the latest run(s) to evals/baselines/ (LAYER=logic|conversation|voice|corpus)
	uv run python -m evals accept $(LAYER)

evals-selftest:   ## the harness tests itself
	uv run pytest evals/selftest -q

evals-discord:    ## post the latest summary.json to #github (needs DISCORD_WEBHOOK_URL)
	scripts/notify-discord.sh --evals

# ---- task board (see docs/tasks.json) --------------------------------------
.PHONY: tasks

tasks:            ## push docs/tasks.json to GitHub issues; ARGS=--dry-run to preview
	uv run python scripts/tasks/sync_issues.py $(ARGS)
