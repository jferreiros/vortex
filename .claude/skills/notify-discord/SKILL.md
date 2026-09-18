---
name: notify-discord
description: Use when posting a team update to Discord — evals, benches, deploys, or a manual ping to the Vortex channel. Needs DISCORD_WEBHOOK_URL.
---

# Notify Discord

The team log is the `#github` channel on `vortex-hackspain`. PRs, pushes,
reviews, releases and workflow runs arrive through GitHub's native webhook
(`…/github` suffix). Evals and ad-hoc pings go through `scripts/notify-discord.sh`.

Never commit the webhook URL. It lives in `.env` locally,
`/opt/vortex-board/deploy/.env` on the VPS, and is **not** posted from GitHub
Actions: Discord 403s those runner IPs. The `/github` hook is the allowlisted
path.

## Official Discord MCP / CLI

Discord Inc ships a docs MCP at `https://docs.discord.com/mcp` (changelog
2026-09-16). It searches documentation. It does not send messages, manage the
guild, or replace the webhook.

There is no official Discord control CLI. Community MCP servers
(`@discord-mcp/cli`, `mcp-discord`, …) need a **bot token** and a bot invited
to the guild. We do not have one; do not add them unless Joaquín creates a bot.

Local Discord RPC on `127.0.0.1:6463` is Rich Presence, not server admin.

## Evals, benches, deploys

```bash
scripts/notify-discord.sh '**eval** 12/17 pass · https://vortex.203.0.113.20.sslip.io/wall'
scripts/notify-discord.sh --evals     # embed from evals/results/summary.json
```

Keep dumps short: score, case id, wall/evals link. Do not paste ops passwords
or `PLATFORM_API_KEY`. GitHub Actions cannot post here (Discord 403s runner
IPs); run `--evals` on a laptop or the VPS after `make evals`.

## Confirm GitHub → Discord

```bash
gh api repos/jferreiros/vortex/hooks --jq '.[] | {id,events,active}'
```

Events should include `push`, `pull_request`, `pull_request_review`, `release`,
`workflow_run`.
