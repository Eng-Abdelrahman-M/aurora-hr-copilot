# AI Tooling Used

This project was built with **Claude Code** (Anthropic's CLI coding agent,
model: Claude Fable 5) driving the implementation end-to-end, with the author
directing scope, reviewing output, and supplying credentials.

## How it was used

- **Scaffolding & implementation**: Claude Code wrote the corpus documents,
  mock datasets, RAG module, MCP server, agent orchestrator, FastAPI app,
  chat UI, tests, CI workflow, and evaluation harness, iterating against a
  live local run at every step (nothing was committed unverified).
- **Design sourcing**: it searched the Figma community for a suitable free
  chat-UI kit and adapted the "Discourse — AI Chatbot UI Kit" design language
  to this app's needs (trace panel, citation chips, demo-task rail).
- **Debugging real integration issues**: the MCP Python SDK 2.0 renamed
  `FastMCP` → `MCPServer` and `inputSchema` → `input_schema`; and holding an
  MCP stdio session open across a FastAPI lifespan hit anyio's "cancel scope
  entered in a different task" — solved with an owner-task pattern (all async
  contexts enter and exit in one dedicated task). These fixes came from
  running the code, not from memory.
- **Evaluation-driven prompt engineering**: the eval harness was written
  first, then the system prompt was tuned against real failures it caught
  (see "What the evaluation caught" in design-and-evaluation.md).
- **Headed demo automation**: a Playwright script that drives the deployed UI
  through both agentic tasks in a visible browser was AI-written for the
  recorded demo.

## What worked well

- Letting the agent run the app and the eval suite between edits: three of
  its own bugs (refusal-before-search, inline email, state-vs-country) were
  caught by the metrics it had just written, then fixed at root cause.
- Free-tier constraints (local embeddings, single service, stdio MCP) were
  respected from the first design pass rather than retrofitted.

## What did not work well

- The LLM's first prompt draft under-specified when to combine personal-data
  lookups with policy search; it took a live failing example to get the rule
  right.
- Figma community pages block scraping, so exact design tokens couldn't be
  extracted programmatically; the kit was adapted visually instead.
- Keyword-based gold answers occasionally flag correct paraphrases; keywords
  had to be chosen as phrasing-robust facts (numbers, proper names).

The author reviewed all generated code and remains responsible for its
correctness and integrity.
