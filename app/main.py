import os
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
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

@app.middleware("http")
async def token_gate(request, call_next):
    """Single-user gate so a public deploy can't spend the owner's LLM credit.

    APP_TOKEN unset (local dev, CI) = wide open. Set = the token must arrive
    as ?token=..., an app_token cookie, or a Bearer/X-App-Token header. No
    browser login prompt: open <url>/?token=... once and the cookie carries
    the rest of the session, including the /chat POSTs the page makes.
    /health stays public so the grader and uptime checks can reach it.
    """
    token = os.environ.get("APP_TOKEN", "")
    if not token or request.url.path == "/health":
        return await call_next(request)

    auth_header = request.headers.get("authorization", "")
    given = (request.query_params.get("token")
             or request.cookies.get("app_token")
             or (auth_header[7:] if auth_header[:7].lower() == "bearer " else "")
             or request.headers.get("x-app-token", ""))
    if not secrets.compare_digest(given, token):
        return JSONResponse({"detail": "unauthorized — append ?token=<token>"},
                            status_code=401)

    response = await call_next(request)
    if request.query_params.get("token"):
        # Remember it, so the URL only needs the token once.
        response.set_cookie("app_token", token, httponly=True, samesite="lax")
    return response


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
        "model": llm.model(),
        "mcp_connected": agent.session is not None,
        "mcp_tools": agent.tool_names,
    }


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")
