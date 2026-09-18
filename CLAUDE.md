# Vortex — Prosper AI (HackSpain 2026)

Voice AI agent for clinic scheduling calls. See `README.md` for the full setup, mode table, and
lane ownership. API spec: `References/openapi.json` (Prosper platform API).

## Platform API credentials

Read once at startup by `vortex/settings.py` via `python-dotenv`, from `.env` (gitignored, never
commit real values — see `.env.example` for the template):

- `PLATFORM_API_KEY` — sent as the `X-Api-Key` header by `vortex/clinic/client.py`. Missing key ->
  `FakeClinicClient` fixtures + dry-run submit client (see README "Modes").
- `PLATFORM_API_BASE_URL` — defaults to `http://localhost:9999`; set to the real desk URL for a
  live call.

The HackSpain team identifier (not consumed by app code, kept for reference only) is noted as a
comment at the top of `.env`.

Manual test call against the live API:

```bash
set -a; source .env; set +a
curl -s -G "$PLATFORM_API_BASE_URL/api/v1/availability" \
  -H "X-Api-Key: $PLATFORM_API_KEY" \
  --data-urlencode "date_from=2026-09-21" \
  --data-urlencode "date_to=2026-09-22" \
  --data-urlencode "specialty_id=general_practice"
```

Note: despite the OpenAPI spec marking `provider_id`/`specialty_id` as optional, the live API
requires at least one of them (422 otherwise).
