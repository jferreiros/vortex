# Platform API spec

`openapi.json` is the organisers' Prosper platform API (0.1.0), taken from the
dashboard API reference on 18 September 2026. It is the source of truth for
every field name in `vortex/clinic/client.py`, `vortex/contract.py` and
`vortex/line/submit.py`; `tests/test_openapi_alignment.py` fails if they drift.

Regenerate with `curl -s "$PLATFORM_API_BASE_URL/api/openapi.json" | python -m json.tool > docs/platform/openapi.json`
(the schema route needs no key; every other route needs `X-Api-Key`).
