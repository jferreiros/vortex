# Vortex — Prosper AI (HackSpain 2026)

Voice AI agent for clinic scheduling calls. See `README.md` for the full setup, mode table, and
lane ownership. API spec: `docs/api/openapi.json` (Prosper platform API).

## Platform API credentials

Read once at startup by `vortex/settings.py` via `python-dotenv`, from `.env` (gitignored, never
commit real values — see `.env.example` for the template):

- `PLATFORM_API_KEY` — sent as the `X-Api-Key` header by `vortex/clinic/client.py`. Missing key ->
  `FakeClinicClient` fixtures + dry-run submit client (see README "Modes").
- `PLATFORM_API_BASE_URL` — defaults to `http://localhost:9999`; set to the real desk URL for a
  live call.

The HackSpain team identifier (not consumed by app code, kept for reference only) is noted as a
comment at the top of `.env`.

To try the live API from the console, use `scripts/api/try_api.py` (`make try-api`): it calls every
readable endpoint, saves each raw JSON response under `api_results/<timestamp>/` (gitignored), and
prints a status line per call. Read-only by design — it never calls `/api/v1/submit/*`. See the
script's docstring for flags (`--specialty-id`, `--name`, `--patient-id`, ...).

Note: despite the OpenAPI spec marking `provider_id`/`specialty_id` as optional on
`/api/v1/availability`, the live API requires at least one of them (422 otherwise) — `try_api.py`
defaults to the first specialty from `/api/v1/specialties` so it works with zero flags.
