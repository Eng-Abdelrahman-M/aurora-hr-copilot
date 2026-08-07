# Design & Evaluation — Aurora HR Copilot

## Architecture

```
┌────────────────────────────── one Render web service ──────────────────────────────┐
│  Browser ── static chat UI (citations + collapsible agent trace)                   │
│     │ POST /chat · GET /health                                                     │
│  FastAPI (app/main.py) — sessions kept in memory (last 8 exchanges)                │
│     │                                                                              │
│  Agent orchestrator (app/agent.py)                 LLM provider (app/llm.py)       │
│   · discovers tools via MCP list_tools()   ──────  OpenAI-compatible chat API      │
│   · bounded tool loop (max 6 steps)                (gpt-4o-mini by default)        │
│   · builds trace + citations                                                       │
│     │ MCP protocol, stdio transport                                                │
│  MCP server subprocess (mcp_server/server.py) — 7 tools                            │
│   · search_policy_documents / get_policy_section  →  RAG index                     │
│   · lookup_employee_profile / check_pto_balance / lookup_benefits_status → mock    │
│   · create_mock_hr_ticket / draft_hr_email        →  mock actions                  │
│  RAG index: Chroma (persistent, .chroma/) + local ONNX MiniLM embeddings           │
│  corpus/ 10 policy docs (md, html, txt) · mock_data/ JSON                          │
└────────────────────────────────────────────────────────────────────────────────────┘
```

## Design choices and why

- **Manual orchestration, no agent framework.** The loop is ~40 lines: LLM →
  tool_calls → MCP call_tool → feed results back, bounded at 6 steps. A
  framework would add dependencies without adding capability at this size.
- **MCP over stdio, single service.** The MCP server runs as a subprocess of
  the web app — free-tier compatible (one Render service), and still a real
  protocol boundary: the agent discovers tools with `list_tools()` and invokes
  them with `call_tool()`; nothing is called as a plain function. Transport
  can move to HTTP later without touching tool code.
- **The RAG index lives inside the MCP server process.** Retrieval is a tool
  (`search_policy_documents`), so the agent's only path to policy text is
  through MCP — which makes the trace complete by construction.
- **Chunking: heading-aware.** Every `##` (md) / `<h2>` (html) / numbered
  heading (txt) becomes one chunk carrying `doc_id`, `title`, `section`
  metadata. Policy documents are naturally section-structured; sections are
  the correct citation unit (`[POL-PTO-001 § 3. Requesting PTO]`). 61 chunks
  from 10 documents — no overlap needed at this granularity, and chunk ids
  are deterministic (`doc_id::index`), so re-ingestion is idempotent.
- **Embeddings: Chroma default (all-MiniLM-L6-v2, ONNX, local).** Free, no
  API key, no rate limits, deterministic; ~80MB downloaded once and cached.
- **Retrieval k = 5** (tool default; the LLM may override per call, and the
  evaluation can force it via `RAG_K`). The ablation below shows why not 1.
- **LLM: gpt-4o-mini** via the OpenAI API — cheap, reliable tool-calling.
  Provider is swappable by env var (`LLM_BASE_URL`) to Groq/OpenRouter/etc.
- **Safety guardrails.**
  - Answers must come from tool results; citation format is enforced by
    prompt and *verified* in evaluation (a doc id in the answer that no tool
    returned counts as ungrounded).
  - Out-of-scope questions (personal tax/legal advice, other companies) are
    declined; workplace questions are always searched before any refusal.
  - Irreversible actions are prevented structurally: both action tools are
    mocks (`create_mock_hr_ticket` writes a local JSON file, `draft_hr_email`
    never sends), and the agent must obtain explicit user confirmation before
    creating a ticket.
  - Sensitive matters (harassment, threats) retrieve the Code of Conduct and
    recommend escalation to People Operations, not self-service fixes.
  - Missing/unknown employee IDs → the agent asks, it never assumes.
- **Failure handling.** MCP tool errors are caught and fed back to the LLM as
  text ("tool unavailable → tell the user, suggest People Operations"), so a
  broken tool degrades to an honest answer instead of a 500.

## MCP tool schemas

Schemas are generated from the Python signatures by the MCP SDK and
discovered by the client at startup (`/health` lists them live). Summary:

| Tool | Arguments | Backing |
|---|---|---|
| search_policy_documents | query: str, k: int = 5 | RAG index |
| get_policy_section | doc_id: str, section_query: str = "" | RAG index |
| lookup_employee_profile | employee_id: str | mock_data/employees.json |
| check_pto_balance | employee_id: str | mock_data/pto_balances.json |
| lookup_benefits_status | employee_id: str | mock_data/benefits.json |
| create_mock_hr_ticket | employee_id, category, summary, details | writes mock_data/tickets.json |
| draft_hr_email | recipient, subject, key_points | returns draft, sends nothing |

## UI design (Figma)

The chat UI adapts the free Figma community kit **"Discourse — AI Chatbot UI
Kit"** (figma.com/community/file/1569991105423787535): dark navigation rail +
light chat canvas, indigo accent, rounded asymmetric bubbles, pill-shaped
chips. Adaptations for this project: citation chips under each answer, a
collapsible per-message *agent trace* panel (tool name, arguments, result
preview), live MCP health in the rail, and one-click buttons for the two demo
tasks (grader reproducibility).

## The two demo agentic tasks

**Task 1 — PTO request guidance** ("I'm EMP003. Can I take 3 days of PTO the
week of September 21? If it's possible, help me get it requested.")
Expected tool sequence:
1. `check_pto_balance(EMP003)` → 2.5 vacation days (insufficient)
2. `search_policy_documents("PTO request …")` → notice rules [POL-PTO-001 §3],
   borrowing up to 3 days [POL-PTO-001 §7]
3. Agent proposes borrowing 0.5 days, asks for confirmation
4. On explicit "yes": `create_mock_hr_ticket(EMP003, pto, …)` → TICKET-####
   (mock), and the answer explains manager approval comes next.

**Task 2 — Remote work abroad** ("I'm EMP002 and I want to work from Portugal
for 6 weeks this fall. Am I allowed, and what do I need to do?")
Expected tool sequence:
1. `lookup_employee_profile(EMP002)` → US-based, remote, manager Sarah Chen
2. `search_policy_documents("working from another country …")` →
   cross-border rules [POL-RW-002 §3] + security-abroad rules [POL-SEC-005 §4]
3. Answer: allowed with People Operations **and** Legal approval, ≥3 weeks
   in advance, ≤90 days/rolling year, home payroll, VPN rules — with next
   steps and an offer to draft the request email (`draft_hr_email` on
   request).

## Evaluation

26 questions across six categories (simple policy, multi-document, tool
tasks, action safety, ambiguous, out-of-scope, escalation) with expected
tools, expected cited documents, and gold keywords:
[evaluation/questions.json](evaluation/questions.json). Grading is
programmatic (no judge model): see metric definitions in
[evaluation/run_eval.py](evaluation/run_eval.py).

Results (live run, gpt-4o-mini, 2026-08-07 —
[full table](evaluation/results.md)):

| Metric | Score |
|---|---|
| Workflow completion | 96% (25/26) |
| Tool selection accuracy | 100% |
| Citation accuracy (policy questions) | 88% |
| Groundedness (no uncited doc references) | 100% |
| Gold-keyword answer match | 96% |
| Action safety (no unconfirmed writes) | 100% |
| Latency p50 / p95 (warm) | 2.5 s / 4.8 s |

Cold start on the free tier adds ~30–60 s to the *first* request only
(service spin-up); warm latency is as above.

### Ablation — retrieval k

Same first-15-question subset, k forced to 1 vs the default 5
([results_k1.md](evaluation/results_k1.md)):

| Metric | k = 5 | k = 1 |
|---|---|---|
| Workflow completion | 100% | 93% |
| Citation accuracy | 93% | 87% |

With k=1 the agent sees a single section, which breaks exactly the
multi-section questions (e.g. carryover + deadline, chair + stipend). k=5
costs ~1k extra prompt tokens and removes that failure class.

### What the evaluation caught during development (kept honest)

- The agent once *refused* a public-Wi-Fi question instead of searching
  (over-eager scope guardrail) — fixed by requiring search-before-refusal.
- It once composed an email inline instead of calling `draft_hr_email` —
  fixed by prompt (drafts must go through the tool so they are traced).
- It once applied the another-*state* rule to Portugal (another *country*) —
  caught by the gold keywords ("People Operations", "Legal"); fixed by k=5
  plus an explicit state-vs-country prompt rule.
