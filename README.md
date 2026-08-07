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
             │    └─ corpus/  (10 policy docs: .md, .html, .txt)
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

## Tests

```bash
pytest tests/ -v      # app boot + /health, MCP tool discovery + real stdio tool calls
```

## Evaluation

```bash
python evaluation/run_eval.py                       # 26 questions -> evaluation/results.md
RAG_K=1 python evaluation/run_eval.py --limit 15 --out results_k1.md   # retrieval ablation
```

Latest results: [evaluation/results.md](evaluation/results.md) — 96% workflow
completion, 100% tool-selection accuracy, 100% groundedness, 100% action
safety, latency p50 2.5s / p95 4.8s.

## Deployment (Render)

[render.yaml](render.yaml) defines a single free-tier web service.
`autoDeploy` is off: the GitHub Actions [CI workflow](.github/workflows/ci.yml)
triggers the deploy hook **only after tests pass**. Set `OPENAI_API_KEY` in the
Render dashboard and `RENDER_DEPLOY_HOOK` as a GitHub Actions secret.

Free-tier note: the instance spins down after ~15 min idle; the first request
cold-starts in ~30–60 s (the UI says so when it happens).

## Demo tasks (reproducible from the UI)

The left sidebar has one-click buttons for the two graded agentic tasks:

1. **PTO request guidance** — "I'm EMP003. Can I take 3 days of PTO the week of
   September 21? …" → `check_pto_balance` + `search_policy_documents`; the
   agent discovers the balance is 2.5 days, finds the borrow-up-to-3-days rule
   [POL-PTO-001 §7], proposes it, and only files the (mock) ticket after you
   confirm.
2. **Remote work abroad** — "I'm EMP002 and I want to work from Portugal for 6
   weeks…" → `lookup_employee_profile` + `search_policy_documents`; the agent
   applies the cross-border rules [POL-RW-002 §3] (People Operations + Legal,
   3 weeks notice), not the domestic ones.

A scripted **headed browser demo** that drives both tasks:
`python scripts/demo_headed.py` (requires `playwright install chromium`).
