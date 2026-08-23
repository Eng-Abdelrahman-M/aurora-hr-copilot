# AI Tooling Used

This project was built by the author using **Claude Code** (Anthropic's CLI
coding agent) as an implementation accelerator. The author owned the problem
framing, architecture, evaluation design, review of every change, and the
deployment; Claude Code was used to turn those decisions into code quickly.

## Division of work

**Author-owned (decided, specified, reviewed, or corrected by hand):**

- **Architecture.** Single-service free-tier design; the decision to put the
  RAG index *behind* an MCP tool rather than calling it directly from the
  orchestrator, so the tool-call trace is complete by construction; manual
  orchestration instead of an agent framework.
- **MCP design.** Which seven tools to expose, their argument shapes, and the
  split between read tools and mock write actions — including the rule that
  `create_mock_hr_ticket` may only fire after explicit user confirmation.
- **Evaluation design.** The 26-question set, its seven categories, and the
  grading criteria (groundedness, citation accuracy, tool selection, action
  safety) were specified first, deliberately before the system prompt was
  tuned, so the prompt was fitted to measured failures rather than to vibes.
- **Review and correction.** Every generated change was read and run before
  it stayed. Several were rejected or rewritten — see "What did not work
  well" below.
- **Deployment and secrets.** Render service, environment variables, the
  deploy-hook wiring so CI only ships on green tests.
- **Scope discipline.** A late cleanup pass removed ~175 lines the agent had
  accumulated (an unrequested `/metrics` endpoint with hand-rolled percentile
  math, a Playwright demo script, a third corpus parser for a single `.txt`
  file, a stale CI workflow). Generated code trends toward more code; keeping
  it skinny was a manual decision.

**Claude Code-generated (under the above direction):**

- First-pass implementation of the RAG module, MCP server, agent loop,
  FastAPI app, chat UI, tests, CI workflow, and evaluation harness.
- The synthetic policy corpus and mock datasets, from the author's outline of
  which topics had to interlock (e.g. the home-office stipend appearing in
  the expense, remote-work, and equipment policies so multi-document
  retrieval could be tested honestly).
- Boilerplate the author would otherwise have typed: JSON schemas, table
  formatting in the eval report, the markdown/HTML section parsers.

## What worked well

- **Evaluation-first, then prompt tuning.** With the harness in place, three
  real behavioral bugs surfaced as failing rows rather than as anecdotes:
  the agent refusing workplace questions before searching, composing emails
  inline instead of through `draft_hr_email`, and applying domestic
  remote-work rules to another country. Each was fixed at root cause in the
  system prompt and re-measured.
- **Debugging live integration issues.** Two problems could only be found by
  running the code: the MCP Python SDK 2.0 rename (`FastMCP` → `MCPServer`,
  `inputSchema` → `input_schema`), and anyio's "cancel scope entered in a
  different task" when holding an MCP stdio session open across a FastAPI
  lifespan. The fix — an owner task that enters and exits every async context
  in one place — was arrived at by reading the traceback, not by asking.
- **Throughput on well-specified work.** Given a clear spec, the corpus, mock
  data, and eval scaffolding took minutes instead of hours.

## What did not work well

- **It over-builds by default.** The agent added a `/metrics` endpoint with
  hand-written percentile arithmetic, a Playwright browser-automation script,
  and a Makefile that nothing used — none of it requested, all of it
  eventually deleted. Left unchecked, generated code grows.
- **A linter/import reorder silently broke config loading.** Moving imports
  to the top of `app/main.py` put `from app import llm` ahead of the `.env`
  loader, so a module-level `MODEL = os.environ.get(...)` captured the
  default and ignored `LLM_MODEL`. Caught by inspection, not by tests; fixed
  by making the lookup lazy so import order can no longer matter.
- **Prompt rules needed real counterexamples.** The first system prompt
  under-specified when to combine personal-data lookups with policy search.
  No amount of restating the rule in the abstract fixed it — it took a
  concrete failing question from the eval set.
- **Stale API knowledge.** The model's memory of the MCP SDK was a version
  behind, which cost a debugging cycle. Verifying against the installed
  package was faster than trusting the generated code.

## Honest summary

Claude Code substantially reduced the time from design to working system, but
every architectural decision, the safety model, the evaluation criteria, and
the final shape of the repository are the author's. The agent wrote a large
share of the lines; it did not decide what the system should be, and its
output was measurably wrong often enough that reviewing it was not optional.
