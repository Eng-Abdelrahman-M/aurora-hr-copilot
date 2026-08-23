import os
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
from app.agent import Agent
from app import llm

ROOT = Path(__file__).resolve().parent.parent

# .env loader (stdlib; keys never live in the repo)
_env = ROOT / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

agent = Agent()
sessions = {}          # session_id -> message history
_unlocked = set()      # session_ids that have supplied APP_TOKEN

LOCKED_REPLY = (
    "This assistant is private - it runs on a personal API key.\n\n"
    "Paste the access token to start. You will only be asked once per session."
)
UNLOCKED_REPLY = (
    "Access granted. Ask me anything about Aurora Dynamics HR policy — PTO, "
    "remote work, expenses, benefits, equipment, leave or workplace conduct. "
    "I look up the policy documents and your (mock) HR records before "
    "answering, and I cite my sources."
)

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

    # Token gate, asked for in the conversation instead of by a login prompt.
    # The LLM is never called while a session is locked, which is the whole
    # point: an unauthorised visitor cannot spend the owner's API credit.
    token = os.environ.get("APP_TOKEN", "")
    if token and sid not in _unlocked:
        granted = secrets.compare_digest(req.message.strip(), token)
        if granted:
            _unlocked.add(sid)
        return {"session_id": sid, "locked": not granted,
                "answer": UNLOCKED_REPLY if granted else LOCKED_REPLY,
                "citations": [], "trace": []}

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
        "model": llm.model(),
        # so you can tell at a glance whether a deploy is actually protected
        "gated": bool(os.environ.get("APP_TOKEN")),
        "mcp_connected": agent.session is not None,
        "mcp_tools": agent.tool_names,
    }


@app.get("/")
async def index():
    # no-cache = revalidate every time (the ETag still yields a cheap 304).
    # Without it browsers heuristically reuse the old page, which silently
    # hides UI changes such as the access-token prompt.
    return FileResponse(ROOT / "static" / "index.html",
                        headers={"Cache-Control": "no-cache"})
