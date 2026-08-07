"""Aurora HR Copilot — web app.

  POST /chat    {message, session_id?} -> {answer, citations, trace, session_id}
  GET  /health  -> app + MCP connectivity status
  GET  /        -> chat UI
"""
import os
import uuid
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent

# Metrics
total_chats: int = 0
total_chat_latency_ms: float = 0.0
latency_history: list[float] = [] # Stores latency for each chat in ms
tool_call_counts: dict[str, int] = defaultdict(int)

# .env loader (stdlib; keys never live in the repo)
_env = ROOT / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from app.agent import Agent  # noqa: E402  (env must load first)
from app import llm  # noqa: E402

agent = Agent(tool_call_counts=tool_call_counts)
sessions = {}  # session_id -> message history  # ponytail: in-memory, per-instance; move to a store if ever >1 replica


@asynccontextmanager
async def lifespan(app):
    await agent.start()
    yield
    await agent.stop()


app = FastAPI(title="Aurora HR Copilot", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


@app.post("/chat")
async def chat(req: ChatRequest):
    global total_chats, total_chat_latency_ms, latency_history
    start_time = time.perf_counter()

    sid = req.session_id or uuid.uuid4().hex[:12]
    history = sessions.setdefault(sid, [])
    result = await agent.run(req.message, history=history)
    history.append({"role": "user", "content": req.message})
    history.append({"role": "assistant", "content": result["answer"]})
    del history[:-16]  # keep the last 8 exchanges

    end_time = time.perf_counter()
    latency_ms = (end_time - start_time) * 1000
    total_chats += 1
    total_chat_latency_ms += latency_ms
    latency_history.append(latency_ms)

    return {"session_id": sid, **result}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model": llm.MODEL,
        "mcp_connected": agent.session is not None,
        "mcp_tools": agent.tool_names,
    }


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/metrics")
async def metrics():
    avg_chat_latency_ms = (total_chat_latency_ms / total_chats) if total_chats > 0 else 0.0

    latency_p50_ms = 0.0
    latency_p95_ms = 0.0

    if latency_history:
        sorted_latencies = sorted(latency_history)
        n = len(sorted_latencies)

        # Calculate P50 (median) and P95 using direct indexing with linear interpolation formula
        # The index formula is (N-1) * P / 100 for a 0-indexed list of N elements
        p50_idx = int((n - 1) * 0.50)
        p95_idx = int((n - 1) * 0.95)

        latency_p50_ms = sorted_latencies[p50_idx]
        latency_p95_ms = sorted_latencies[p95_idx]

    return {
        "total_chats": total_chats,
        "tool_calls": dict(tool_call_counts),
        "avg_chat_latency_ms": avg_chat_latency_ms,
        "latency_p50_ms": latency_p50_ms,
        "latency_p95_ms": latency_p95_ms,
    }
