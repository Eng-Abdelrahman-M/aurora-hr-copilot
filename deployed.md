# Deployment

- **Deployed URL:** https://aurora.aothman.org
- **Health endpoint:** https://aurora.aothman.org/health — app status, model,
  MCP connectivity, the discovered tool list, and whether the access gate is
  active. Public, no token needed.

## Access (for the grader)

This is a single-user instance running on the author's own LLM API credit, so
the assistant asks for an access token **in the chat itself**. There is no
login page and no browser password prompt:

1. Open the deployed URL — the page loads normally.
2. The assistant's first message asks for the access token.
3. Paste the token (it is in the submission form) and send it.
4. It replies "Access granted" and the session is unlocked for good.

Until the right token is pasted, the app answers every message with the same
request and **never calls the LLM**, so an unauthorised visitor cannot spend
the owner's API credit.

`/health` is ungated so connectivity and MCP status can be checked without the
token. It also reports whether the gate is active:

```bash
curl -s <deployed-url>/health
# {"status":"ok", ..., "gated":true, "mcp_connected":true, "mcp_tools":[...]}
```

`"gated": false` means `APP_TOKEN` is missing from the environment and the app
is open to anyone. `render.yaml` declares it with `sync: false`, so Render does
**not** supply a value — it must be entered in the dashboard under Environment
after the first deploy.

From an API client, send the token as the first `/chat` message and reuse the
`session_id` it returns:

```bash
curl -X POST <deployed-url>/chat -H 'Content-Type: application/json' -d '{"message":"<token>"}'
# -> {"session_id":"abc123...", "locked":false, "answer":"Access granted. ..."}
curl -X POST <deployed-url>/chat -H 'Content-Type: application/json' -d '{"message":"How many PTO days carry over?","session_id":"abc123..."}'
```

The gate is off by default: with `APP_TOKEN` unset (local development and CI)
the app is wide open, so nothing about the local run or the tests changes.

## How it is deployed

Self-hosted on a VPS, managed by [Dokploy](https://dokploy.com):

```
Internet ─ 443 ─> Traefik (Dokploy) ─ dokploy-network ─> app container :8000
                    │ Let's Encrypt certificate, auto-renewed
                    └ HTTP :80 redirects to HTTPS
```

- One container from this repo's [Dockerfile](Dockerfile), built on the
  server. The image bakes the Chroma index and the ONNX embedding model at
  build time, so a fresh container answers its first request immediately.
- The container publishes **127.0.0.1:8100 only** — it is not reachable from
  the internet except through Traefik.
- Routing is by Traefik labels on the container
  (a `Host` rule for aurora.aothman.org → service port 8000), issued a certificate
  by the `letsencrypt` resolver.
- Secrets (`OPENAI_API_KEY`, `APP_TOKEN`) come from Dokploy's environment
  settings, never from the repository.

Redeploy after a push: Dokploy pulls the repo and runs
`docker compose up -d --build` for the service.

**No cold starts.** The container has `restart: unless-stopped` and stays
resident, so every request is a warm request — unlike a free tier that spins
down after idling. Measured warm latency is p50 3.5 s / p95 6.1 s
(see [evaluation/results.md](evaluation/results.md)).

## Local run

```bash
cp .env.example .env      # OPENAI_API_KEY, and APP_TOKEN if you want the gate
docker compose up --build # http://localhost:8100
```
