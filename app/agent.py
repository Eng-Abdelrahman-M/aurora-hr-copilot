"""Agent orchestrator: interprets intent, discovers MCP tools, runs a bounded
tool loop, and returns a final answer plus an operational trace + citations.

The MCP server runs as a subprocess over stdio; tools are discovered with
list_tools() and invoked with call_tool() — never called as plain functions.
"""
import asyncio
import json
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app import llm

ROOT = Path(__file__).resolve().parent.parent
MAX_STEPS = 6

SYSTEM_PROMPT = """You are Aurora HR Copilot, the internal HR assistant of Aurora Dynamics.

Rules:
- Answer ONLY from tool results. For any policy question, call
  search_policy_documents first (get_policy_section for full detail). Never
  answer policy questions from memory.
- Cite sources for every policy claim, inline, as [doc_id § section], e.g.
  [POL-PTO-001 § 3. Requesting PTO]. Only cite documents that actually came
  back from tools.
- Anything about the workplace — devices, security, Wi-Fi, equipment, office,
  travel, conduct — IS in scope: search first, never refuse before searching.
  Only decline when retrieval comes back irrelevant, or the question is
  clearly outside Aurora Dynamics HR (personal legal/tax/medical advice,
  other companies' policies) — then say so plainly, do not guess, and point
  to People Operations when appropriate.
- Distinguish policy facts (cited) from your recommendations (introduce with
  "Recommendation:").
- Personal data (profiles, balances, benefits) comes only from the lookup
  tools. If an employee ID is missing or not found, ask the user for it
  (format EMP###) instead of assuming. But only ask when the answer truly
  depends on personal records — a general policy question ("what trainings
  are required", "what is the PTO accrual") needs no ID: just search.
- HR workflow requests (PTO requests, remote work, expenses, benefits
  changes) need BOTH sides: the employee's data (lookup tools) AND the
  governing policy (search_policy_documents) — always retrieve both before
  concluding, and check the policy for alternatives (e.g. borrowing days,
  floating holidays) before saying something is impossible.
- Location questions: working from another US state and working from another
  COUNTRY are governed by different rules — for anywhere abroad, apply the
  "Working from another country" rules (cross-border approval), not the
  domestic ones.
- create_mock_hr_ticket and draft_hr_email are mock actions. NEVER call
  create_mock_hr_ticket unless the user has explicitly confirmed in this
  conversation that they want the ticket. Propose it first and ask. But ask
  exactly ONCE: when the user's latest message already gives explicit consent
  ("yes", "go ahead", "create it"), create the ticket NOW — asking again is
  wrong.
- When the user asks for an email or message draft, generate it THROUGH the
  draft_hr_email tool (so the action is traced) and present the returned
  draft — never compose the email yourself.
- Sensitive matters (harassment, discrimination, threats, medical crises):
  ALWAYS retrieve the Code of Conduct first (search_policy_documents), cite
  the reporting/escalation paths it gives, and recommend escalation to
  People Operations rather than self-service fixes.
- Be concise and structured. Plain text, short paragraphs or dashes.
"""


class Agent:
    """Holds one MCP session and the discovered tool schemas."""

    def __init__(self):
        self.session = None
        self.tools = []          # OpenAI-format tool schemas
        self.tool_names = []
        self._task = None
        self._ready = None
        self._shutdown = None
        self._error = None

    async def start(self):
        """Spawn an owner task that holds the MCP session open. All async
        contexts are entered AND exited in that one task (anyio cancel scopes
        must not cross tasks)."""
        self._ready, self._shutdown = asyncio.Event(), asyncio.Event()
        self._task = asyncio.create_task(self._owner())
        await self._ready.wait()
        if self._error:
            raise self._error

    async def _owner(self):
        try:
            async with AsyncExitStack() as stack:
                params = StdioServerParameters(
                    command=sys.executable, args=["-m", "mcp_server.server"],
                    cwd=str(ROOT))
                read, write = await stack.enter_async_context(stdio_client(params))
                self.session = await stack.enter_async_context(ClientSession(read, write))
                await self.session.initialize()
                listed = await self.session.list_tools()
                self.tools = [{
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description or "",
                        "parameters": t.input_schema,
                    },
                } for t in listed.tools]
                self.tool_names = [t.name for t in listed.tools]
                self._ready.set()
                await self._shutdown.wait()
        except Exception as e:
            self._error = e
            self._ready.set()
        finally:
            self.session = None

    async def stop(self):
        if self._task:
            self._shutdown.set()
            await self._task

    async def _call_tool(self, name, args):
        """Call one MCP tool; failures come back as text the LLM can act on."""
        try:
            result = await self.session.call_tool(name, args)
            return "\n".join(c.text for c in result.content if c.type == "text")
        except Exception as e:  # tool/transport failure → graceful degradation
            return f"TOOL ERROR: {name} is unavailable ({e}). Tell the user and suggest contacting People Operations."

    async def run(self, user_message, history=None):
        """One agentic turn. Returns {answer, trace, citations}."""
        from datetime import date
        messages = [{"role": "system",
                     "content": SYSTEM_PROMPT + f"\nToday's date: {date.today().isoformat()}."}]
        messages += history or []
        messages.append({"role": "user", "content": user_message})

        trace, citations = [], []
        for _ in range(MAX_STEPS):
            msg = llm.chat(messages, tools=self.tools)
            if not msg.tool_calls:
                return {"answer": msg.content or "", "trace": trace,
                        "citations": _dedupe(citations)}
            messages.append({"role": "assistant", "content": msg.content,
                             "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                result = await self._call_tool(tc.function.name, args)
                trace.append({"tool": tc.function.name, "arguments": args,
                              "result_preview": result[:400]})
                citations += _extract_citations(tc.function.name, result)
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": result[:6000]})

        return {"answer": "I couldn't complete this request within the step "
                          "limit. Please rephrase or contact People Operations.",
                "trace": trace, "citations": _dedupe(citations)}


def _extract_citations(tool_name, result):
    if tool_name not in ("search_policy_documents", "get_policy_section"):
        return []
    try:
        hits = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(hits, list):
        return []
    return [{"doc_id": h["doc_id"], "title": h["title"], "section": h["section"],
             "snippet": (h.get("snippet") or h.get("text", ""))[:300]}
            for h in hits if isinstance(h, dict) and "doc_id" in h]


def _dedupe(citations):
    seen, out = set(), []
    for c in citations:
        key = (c["doc_id"], c["section"])
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out
