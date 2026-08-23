# Aurora HR Copilot

An agentic AI system for HR policy and operations at the (hypothetical) company
**Aurora Dynamics**. It combines Retrieval-Augmented Generation over a corpus of
10 policy documents with an agent orchestrator that discovers and calls tools on
an **MCP server** (employee records, PTO balances, benefits, mock HR actions),
and answers with inline citations and a visible tool-call trace.

**Deployed app:** see [deployed.md](deployed.md) · **Design & evaluation:**
[design-and-evaluation.md](design-and-evaluation.md) · **AI tooling used:**
[ai-tooling.md](ai-tooling.md)

## Architecture (one service, free-tier friendly)

```
Browser (chat UI, static/index.html)
   │  POST /chat, GET /health
FastAPI app (app/main.py)
   └─ Agent orchestrator (app/agent.py) ── OpenAI-compatible LLM (app/llm.py)
        │  MCP protocol over stdio (discovery + tool calls)
        └─ MCP server subprocess (mcp_server/server.py) — 7 tools
             ├─ RAG index: Chroma + local ONNX MiniLM embeddings (app/rag.py)
             │    └─ corpus/  (10 policy docs: .md, .html)
             └─ mock_data/  (employees, PTO balances, benefits, tickets)
```

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env            # put your OPENAI_API_KEY in .env
```

The LLM provider is configurable: any OpenAI-compatible endpoint works via
`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` (e.g. Groq or OpenRouter free
tiers). Embeddings are **local and free** (Chroma's ONNX MiniLM) — no key
needed for indexing or retrieval.

## Run locally

```bash
python -m app.rag                       # build the index + self-check (first run downloads ~80MB model)
uvicorn app.main:app --port 8100        # then open http://localhost:8100
```

## Run with Docker

```bash
cp .env.example .env             # put your OPENAI_API_KEY in it
docker compose up --build        # then open http://localhost:8100
```

The image bakes the Chroma index and the MiniLM embedding model at build
time, so the container answers the first request without downloading
anything. `.env` is in `.dockerignore` — the key is passed at run time, never
baked into the image. Mock HR tickets the agent creates land in `mock_data/`
on the host via a bind mount, so they survive restarts and are easy to show
in a demo.

## Tests

```bash
pytest tests/ -v      # app boot + /health, MCP tool discovery + real stdio tool calls
```

## Evaluation

```bash
python evaluation/run_eval.py                    # 26 questions -> evaluation/results.md
RAG_K=1 python evaluation/run_eval.py --out results_k1.md   # ablation (summary lives in results.md)
```

Latest results: [evaluation/results.md](evaluation/results.md) — 96% workflow
completion, 100% tool-selection accuracy, 100% citation accuracy, 100%
groundedness, 100% action safety, latency p50 3.5s / p95 6.1s.

## Deployment (Render)

[render.yaml](render.yaml) defines a single free-tier web service.
`autoDeploy` is off: the GitHub Actions [CI workflow](.github/workflows/ci.yml)
triggers the deploy hook **only after tests pass**. Set `OPENAI_API_KEY` in the
Render dashboard and `RENDER_DEPLOY_HOOK` as a GitHub Actions secret.

The deployed instance is gated by a token (`APP_TOKEN`) because it runs on a
personal LLM key. There is no login form: open `<url>/?token=<token>` once and
the app sets a cookie for the rest of the session. API clients can send it as
`Authorization: Bearer <token>` or `X-App-Token: <token>` instead. `/health`
stays public. Locally, leave `APP_TOKEN` unset and there is no gate at all.
See [deployed.md](deployed.md) for the token.

Free-tier note: the instance spins down after ~15 min idle; the first request
cold-starts in ~30–60 s (the UI says so when it happens).

## Demo tasks (reproducible from the UI)

The left sidebar has one-click buttons for the two graded agentic tasks:

1. **PTO request guidance** — "Hi, I'm Abdelrahman Othman. Can I take 3 days
   off the week of September 21? …" → `check_pto_balance` +
   `search_policy_documents`; the agent resolves the name to a record, finds
   the balance is 2.5 days, finds the borrow-up-to-3-days rule
   [POL-PTO-001 §7], proposes it, and only files the (mock) ticket after you
   confirm.
2. **Remote work abroad** — "I want to work from Portugal for six weeks this
   fall — does my role and work setup allow that? …" →
   `lookup_employee_profile` + `search_policy_documents`; the agent applies
   the cross-border rules [POL-RW-002 §3] (People Operations + Legal, 3 weeks
   notice), not the domestic ones.

Every people-data tool accepts a name or an employee ID, so you never have to
know an ID to use the app.

### Scripted demo

[scripts/demo.py](scripts/demo.py) drives both tasks in a visible browser so
you can narrate over it — it types, sends, waits for each answer, and expands
the agent-trace panel.

```bash
pip install -r requirements-dev.txt && playwright install chromium
python scripts/demo.py                                        # local
DEMO_URL=<deployed-url> DEMO_TOKEN=<token> python scripts/demo.py   # deployed
PAUSE=0 python scripts/demo.py                                # advance on Enter
```
