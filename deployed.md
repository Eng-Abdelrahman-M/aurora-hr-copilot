# Deployment

- **Deployed URL:** _pending first deploy — see below_
- **Health endpoint:** `<deployed-url>/health` — returns app status, model,
  MCP connectivity and the discovered tool list. **Public, no login needed.**

## Access (for the grader)

This is a single-user instance running on the author's own LLM API credit, so
the chat UI and `/chat` are gated by a token. **There is no login form** —
just open the URL with the token attached:

```
<deployed-url>/?token=<token>
```

The token is in the submission form. The app sets a cookie on that first
request, so every later click and every `/chat` call the page makes carries it
automatically; you only need the `?token=` once.

From an API client, send it as a header instead:

```bash
curl -H "Authorization: Bearer <token>" <deployed-url>/    # or X-App-Token: <token>
curl -X POST <deployed-url>/chat -H "Authorization: Bearer <token>"      -H 'Content-Type: application/json'      -d '{"message":"How many PTO days carry over?"}'
```

`/health` is deliberately ungated, so connectivity and MCP status can be
checked without the token.

The gate is off by default: with `APP_TOKEN` unset (local development and CI)
the app is wide open, so nothing about the local run or the tests changes.

## How to deploy (Render free tier)

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
