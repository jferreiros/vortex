# Deploy — the call socket on a machine that stays up

This publishes the Vortex WebSocket server on a fixed HTTPS address, behind the
Traefik that Coolify already runs on this host. No laptop, no ngrok, no URL that
changes when someone closes a lid.

---

## The endpoint

Paste this into the dashboard, **Settings → Integration → Endpoint**:

```
wss://line.vortex.jferreiros.com/ws
```

Scheme `wss://`, **path `/ws` included**. `https://line.vortex.jferreiros.com`
is not the endpoint — the docs call forgetting the path the most common mistake
in the whole challenge, and the platform accepts only `wss://` or `ws://`.

While the DNS record below does not exist yet, the same service answers on a
name that needs no DNS at all:

```
wss://line.167.233.80.47.sslip.io/ws
```

`sslip.io` resolves any `*.167.233.80.47.sslip.io` to this machine, so that host
works the moment the container starts, with its own Let's Encrypt certificate.
Both names route to the same container; either one is safe to hand over.

---

## The DNS record — create it by hand

**Not created by this deployment.** Add these at whoever hosts `jferreiros.com`
(the apex currently points at Vercel, `216.198.79.1`):

```
line.vortex.jferreiros.com.   300   IN   A      167.233.80.47
```

Optional, only if you have confirmed inbound IPv6 reaches this box from outside:

```
line.vortex.jferreiros.com.   300   IN   AAAA   2a01:4f8:1c18:8326::1
```

Both addresses belong to this machine and Traefik listens on both stacks
(`0.0.0.0:443` and `[::]:443`, both verified answering). The machine's own
answer to `curl -s https://ifconfig.me` is the IPv6 one, `2a01:4f8:1c18:8326::1`,
because it prefers IPv6 outbound; `curl -s -4 https://ifconfig.me` gives the
IPv4, `167.233.80.47`. **Create the A record first.** An AAAA record that is not
actually reachable from the internet will make Let's Encrypt fail the HTTP-01
challenge over IPv6 and no certificate will be issued.

Traefik requests the certificate on its own the first time a request arrives for
the host. Give it ten seconds, then retry.

---

## Deploy

```bash
deploy/deploy.sh
```

That is the whole thing: fetch `main`, rebuild the image, restart the container,
wait for it to report healthy, check the public endpoint, and dial it with a
fake call. It prints a green line and the endpoint when all five pass, and a red
line naming the failed step when they do not. Exit code 0 means the endpoint is
ready for a run.

```bash
deploy/deploy.sh --skip-pull     # deploy the working tree as it stands
deploy/deploy.sh --check-only    # verify what is already running, change nothing
```

Point it at a different host with `VORTEX_PUBLIC_HOST=line.vortex.jferreiros.com deploy/deploy.sh`.
It defaults to the sslip.io name, which is the one that works without DNS.

### First time on a fresh machine

```bash
cp deploy/.env.example deploy/.env    # then fill in the keys you have
deploy/deploy.sh
```

Requirements: the `coolify` Docker network must exist (it does — Traefik is on
it), and your user must be able to talk to the Docker daemon:

```bash
groups | grep -q docker || sudo usermod -aG docker "$USER"   # then log in again
```

### What the container gets

Keys come in as environment variables from `deploy/.env`, which is git-ignored.
Nothing secret is baked into the image and nothing secret is committed: every
`COPY` in `deploy/Dockerfile` names an explicit path, so there is no way for a
`.env` to ride into a layer. `deploy/.env.example` lists every variable.

With no keys at all the server still starts, on fake clinic data and the stub
voice pipeline. `GET /health` says which mode is live:

```bash
curl -s https://line.167.233.80.47.sslip.io/health
```

---

## Logs

```bash
docker logs -f vortex-line                                 # the server
docker exec vortex-line tail -f /app/logs/calls.jsonl      # one JSON line per call event
curl -s https://line.167.233.80.47.sslip.io/calls | jq     # recent calls grouped by call_id
docker compose -f deploy/compose.yaml ps                   # state and health
```

The call log lives in the `vortex-line_line-logs` volume, so it survives a
rebuild. Container logs roll at 20 MB × 5 files.

---

## It stopped answering at three in the morning

Work down this list. Each step tells you which half of the path is broken.

1. **`deploy/deploy.sh --check-only`.** It walks the same path a call takes and
   names the first thing that is wrong. Start here.

2. **Is the container up?**
   `docker compose -f deploy/compose.yaml ps`
   `restart: unless-stopped` brings it back after a crash or a reboot, so
   `Restarting` in a loop means the app is dying at startup — `docker logs
   vortex-line --tail 50`.

3. **Is the app healthy inside the container?**
   `docker inspect -f '{{.State.Health.Status}}' vortex-line`
   That probe is the app's own `/health`. Healthy here plus a failure outside
   means the problem is Traefik or DNS, not us.

4. **Traefik answered `404`.** No router matched the host you asked for. Either
   you used a hostname that is not in the `Host()` labels in
   `deploy/compose.yaml`, or the container lost its labels — redeploy.

5. **Traefik answered `503`.** A router matched but found no backend. Almost
   always the container fell off the `coolify` network:
   `docker inspect -f '{{json .NetworkSettings.Networks}}' vortex-line`.
   Redeploy; do not recreate the network.

6. **Certificate errors.** For `line.vortex.jferreiros.com`, check the A record
   exists and resolves to `167.233.80.47`. Let's Encrypt rate-limits repeated
   failures for the same name, so fix DNS before retrying in a loop. The
   sslip.io name always works and is the escape hatch when a run is about to
   start.

7. **`/health` returns 200 but calls fail.** The HTTP path works and the
   WebSocket upgrade does not. Reproduce it in one line:
   `uv run python scripts/fake_caller.py --url wss://line.167.233.80.47.sslip.io/ws --calls 1`
   No middleware is applied to the HTTPS routers precisely so there is nothing
   here that can eat an upgrade; if you added one, that is the first suspect.

8. **Calls get cut part-way through.** A call runs up to three minutes and sends
   a frame every 20 ms, so the connection is never idle and Traefik's idle
   timeout should not fire. If it does, that is a Traefik-level setting — it
   belongs to Coolify, shared with every other service on this box. Do not
   change it without asking the machine's owner.

9. **`clinic: fake` when you expected `live`.** The keys are read once at
   startup. Edit `deploy/.env`, then `deploy/deploy.sh --skip-pull`.

A run holds ten sockets open at once, twenty on problem 2. Everything here is
per-socket, so concurrency is not a deployment concern — but do check
`docker stats vortex-line` during the first big run. The container is capped at
4 GB on a 22 GB machine.

---

## The board lives somewhere else

`deploy/deploy.sh` deploys the call socket only. The jury wall and the ops
board (`vortex.167.233.80.47.sslip.io`) run from a separate clone that root
owns, built from `Dockerfile.board` with `deploy/compose.yml`:

```
/opt/vortex-board          the clone; deploy/.env holds VORTEX_OPS_PASSWORD
```

A merge into `main` does not reach the wall on its own. To redeploy the board:

```bash
ssh vps
cd /opt/vortex-board
git fetch origin main && git reset --hard origin/main
docker compose -f deploy/compose.yml up -d --build
```

Then open `https://vortex.167.233.80.47.sslip.io/wall`. The container exposes
no host port, so `curl 127.0.0.1:8080` on the box says nothing: check through
Traefik.

## Living next to the other services

This host runs other services, including one in real use. This deployment stays
in its own lane and changes nothing that was already running:

- Its own compose project (`vortex-line`), container (`vortex-line`), image and
  volume.
- Traefik router and middleware names prefixed `vortexline-`, chosen so they do
  not collide with the `vortex-*` names the `vortex-board` deployment already
  uses.
- It publishes **no host port**. It joins the existing `coolify` network and is
  reached only through Traefik.
- No change to Traefik, to Coolify, or to the machine's network configuration.
