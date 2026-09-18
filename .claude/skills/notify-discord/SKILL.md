---
name: notify-discord
description: Use when posting a team update to Discord — evals, benches, PRs, deploys, or a manual ping to the Vortex channel. Needs DISCORD_WEBHOOK_URL.
---

# Notify Discord

The team channel is a Discord webhook. Never commit the URL. It lives in
`.env` locally, `/opt/vortex-board/deploy/.env` on the VPS, and the GitHub
secret `DISCORD_WEBHOOK_URL`.

## One-shot ping (evals, benches, deploys)

```bash
test -n "$DISCORD_WEBHOOK_URL"
curl -sS -X POST "$DISCORD_WEBHOOK_URL" \
  -H 'Content-Type: application/json' \
  -d "$(python3 -c 'import json,sys; print(json.dumps({"content": sys.argv[1][:1900]}))' "$MSG")"
```

Keep eval dumps short: score, case id, link to `/evals`. Do not paste ops
passwords or `PLATFORM_API_KEY`.

Example:

```bash
MSG='**eval** 12/17 pass · wall https://vortex.203.0.113.20.sslip.io/wall'
curl -sS -X POST "$DISCORD_WEBHOOK_URL" \
  -H 'Content-Type: application/json' \
  -d "$(python3 -c 'import json,sys; print(json.dumps({"content": sys.argv[1][:1900]}))' "$MSG")"
```

## Hook GitHub → #github (PRs, pushes)

Once the webhook URL exists:

```bash
gh api repos/jferreiros/vortex/hooks \
  -f name=web \
  -f 'config[url]='"$DISCORD_WEBHOOK_URL/github" \
  -f 'config[content_type]=json' \
  -F 'config[insecure_ssl]=0' \
  -F active=true \
  -f events[]=push \
  -f events[]=pull_request \
  -f events[]=release \
  -f events[]=workflow_run
```

The `/github` suffix is required. Discord formats those payloads; a raw
webhook shows JSON.

Confirm with `gh api repos/jferreiros/vortex/hooks`. Star the repo once as a
test ping.

## Cursor MCP

There is no Discord MCP in this session and none is needed for evals or PRs.
Agents post with the curl above. A Discord bot MCP only helps if we later want
to list channels or read history.
