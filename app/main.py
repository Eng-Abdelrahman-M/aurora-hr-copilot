"""Aurora HR Copilot — web app.

  POST /chat    {message, session_id?} -> {answer, citations, trace, session_id}
  GET  /health  -> app + MCP connectivity status
  GET  /        -> chat UI
"""
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent

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

agent = Agent()
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
    sid = req.session_id or uuid.uuid4().hex[:12]
    history = sessions.setdefault(sid, [])
    result = await agent.run(req.message, history=history)
    history.append({"role": "user", "content": req.message})
    history.append({"role": "assistant", "content": result["answer"]})
    del history[:-16]  # keep the last 8 exchanges
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
