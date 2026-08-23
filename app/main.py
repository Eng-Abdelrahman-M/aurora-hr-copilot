import os
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
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
sessions = {}

@asynccontextmanager
async def lifespan(app):
    await agent.start()
    yield
    await agent.stop()


app = FastAPI(title="Aurora HR Copilot", lifespan=lifespan)

_basic = HTTPBasic(auto_error=False)


def auth(creds: HTTPBasicCredentials | None = Depends(_basic)):
    """Single-user gate so a public deploy can't spend the owner's LLM credit.

    APP_PASSWORD unset (local dev, CI) = wide open. Set = HTTP Basic; the
    browser prompts natively, any username works. /health stays public so
    the grader and uptime checks can reach it.
    """
    password = os.environ.get("APP_PASSWORD", "")
    if not password:
        return
    if not creds or not secrets.compare_digest(creds.password, password):
        raise HTTPException(401, "Unauthorized",
                            headers={"WWW-Authenticate": "Basic"})


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


@app.post("/chat")
async def chat(req: ChatRequest, _=Depends(auth)):
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
        "model": llm.model(),
        "mcp_connected": agent.session is not None,
        "mcp_tools": agent.tool_names,
    }


@app.get("/")
async def index(_=Depends(auth)):
    return FileResponse(ROOT / "static" / "index.html")
