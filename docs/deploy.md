# Where the server lives

The WebSocket the organisers dial no longer runs on anyone's laptop. It runs as
a container on the team server, published over HTTPS by the Traefik that is
already on that machine, and it comes back on its own after a crash or a reboot.

**The endpoint for the dashboard (Settings → Integration):**

```
wss://line.vortex.jferreiros.com/ws
```

Scheme `wss://`, path `/ws` included. Until the DNS record for that name exists,
use the name that needs no DNS:

```
wss://line.167.233.80.47.sslip.io/ws
```

**To deploy the latest `main`:**

```bash
deploy/deploy.sh
```

Everything else — the image, the Traefik labels, the DNS record to create, how
to read the logs and what to check first when it stops answering at three in the
morning — is in [`deploy/README.md`](../deploy/README.md).

`make run`, `make dev` and `make tunnel` still work for local development. The
deployment does not replace them; it replaces the tunnel for the people dialling
us from outside.
