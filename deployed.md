# Deployment

- **Deployed URL:** _pending first deploy — see below_
- **Health endpoint:** `<deployed-url>/health` — returns app status, model,
  MCP connectivity and the discovered tool list. **Public, no login needed.**

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

## How to deploy (VPS that already runs a reverse proxy)

If the host already terminates TLS for other sites (gitea, odoo, ...), do not
start the bundled Caddy — it cannot bind 80/443 while the existing proxy holds
them. Run the app alone and add one site block to the proxy you already have.

```bash
cd aurora-hr-copilot
cat > .env <<'ENV'
OPENAI_API_KEY=sk-...
APP_TOKEN=<the access token>        # without this the app is PUBLIC
ENV

docker compose up -d --build        # binds 127.0.0.1:8100 only
curl -s localhost:8100/health       # expect "gated":true
```

Then, in the existing Caddyfile:

```
aurora.aothman.org {
	reverse_proxy 127.0.0.1:8100
}
```

and reload it (`caddy reload --config /etc/caddy/Caddyfile`, or
`systemctl reload caddy`). Confirm from outside:

```bash
curl -s https://aurora.aothman.org/health     # {"status":"ok","gated":true,...}
```

## How to deploy (VPS with nothing else on 80/443)

The app runs as two containers: itself, and Caddy terminating TLS in front of
it. Caddy obtains and renews the certificate automatically.

Prerequisites: a DNS A record for the chosen domain pointing at the VPS, and
ports 80 and 443 open.

```bash
ssh user@your-vps
git clone https://github.com/Eng-Abdelrahman-M/aurora-hr-copilot.git
cd aurora-hr-copilot

cat > .env <<'ENV'
DOMAIN=hr.example.org
OPENAI_API_KEY=sk-...
APP_TOKEN=<the access token>
ENV

docker compose -f docker-compose.prod.yml up -d --build
```

The first build takes a few minutes: it installs dependencies and bakes the
Chroma index plus the ~80 MB embedding model into the image, so the container
answers its first request immediately.

Verify:

```bash
curl -s https://hr.example.org/health     # {"status":"ok", "gated":true, ...}
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f app
```

`APP_TOKEN` and `DOMAIN` are declared with `:?`, so the stack refuses to start
rather than coming up unprotected or without a certificate.

Update after a push:

```bash
git pull && docker compose -f docker-compose.prod.yml up -d --build
```

**No cold starts.** `restart: unless-stopped` keeps it running, so the first
request after an idle period is as fast as any other — unlike the free tier
described below.

## How to deploy (Render free tier — alternative)

1. Create a new **Blueprint** on Render pointing at this repository
   ([render.yaml](render.yaml) defines the service), or create a single
   Python web service manually with:
   - Build: `pip install -r requirements.txt && python -m app.rag`
   - Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
2. Set `OPENAI_API_KEY` and `APP_TOKEN` in the Render dashboard. Neither
   value is ever committed — `render.yaml` marks both `sync: false`.
3. Turn auto-deploy **off** and copy the service's *deploy hook* URL into the
   GitHub repo as the `RENDER_DEPLOY_HOOK` Actions secret — CI then deploys
   only when tests pass.
4. Put the resulting URL here and in the README.

## Cold starts

The free tier spins the instance down after ~15 minutes of inactivity. The
first request after that takes ~30–60 s (instance boot + index load); the
chat UI surfaces this ("service may be cold-starting"). Warm-request latency
is p50 ≈ 2.5 s, p95 ≈ 4.8 s (see evaluation/results.md). The RAG index and
embedding model are built/downloaded at **build** time, not per cold start.
