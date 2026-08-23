import os
import re
import secrets
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
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
sessions = {}          # session_id -> message history
_unlocked = {}         # session_id -> last-activity timestamp

# Abuse limits. All three exist for one reason: the deployment runs on a
# personal API key, so an unattended public URL must not be able to drain it.
SESSION_TTL = int(os.environ.get("SESSION_TTL", 1800))       # 30 min idle
RATE_LIMIT = int(os.environ.get("RATE_LIMIT", 40))           # requests...
RATE_WINDOW = int(os.environ.get("RATE_WINDOW", 300))        # ...per 5 min, per IP
MAX_MESSAGE_CHARS = int(os.environ.get("MAX_MESSAGE_CHARS", 2000))

_hits = {}             # client ip -> deque of request timestamps

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

EXPIRED_REPLY = (
    "This session expired after a period of inactivity.\n\n"
    "Paste the access token again to continue."
)
RATE_LIMITED_REPLY = (
    "Too many requests from this address. This is a demo instance running on a "
    "personal API key, so it is rate limited. Please wait a few minutes and "
    "try again."
)
TOO_LONG_REPLY = (
    f"That message is too long (limit {MAX_MESSAGE_CHARS} characters). "
    "Please ask a shorter HR question."
)


# Deterministic scope guard. The system prompt also tells the agent to stay in
# its lane, but a prompt rule is advisory — it can be talked around. These
# patterns are checked in code, before the model is called at all, so a
# jailbreak or a "write me a program" costs nothing and cannot be negotiated
# with. Deliberately narrow: it must never catch a real HR question, so it
# targets instruction-override phrasing and clearly non-HR deliverables only.
_BLOCKED = re.compile(
    r"""
      ignore\s+(all\s+|any\s+)?(previous|prior|earlier|above)\s+(instructions|prompts?|rules)
    | disregard\s+(all\s+|your\s+)?(previous|prior|above|the)\s+(instructions|rules|prompt)
    | (reveal|show|print|repeat|output)\s+(me\s+)?(your|the)\s+(system\s+)?(prompt|instructions)
    | what\s+(is|are)\s+your\s+(system\s+)?(prompt|instructions)
    | you\s+are\s+now\s+(a|an|no\s+longer)
    | (pretend|act)\s+(to\s+be|as\s+if|as\s+a|as\s+an)\b
    | \bDAN\s+mode\b | \bjailbreak\b | developer\s+mode
    | write\s+(me\s+)?(a|an|some)?\s*(python|javascript|java|c\+\+|sql|bash|shell)\b
    | write\s+(me\s+)?(a|an)\s+(poem|song|story|essay|novel|joke|rap)
    | (solve|calculate)\s+.{0,20}(equation|integral|derivative|homework)
    | translate\s+.{0,30}\b(into|to)\s+(spanish|french|german|arabic|chinese|japanese)
    """,
    re.IGNORECASE | re.VERBOSE,
)

OFF_TOPIC_REPLY = (
    "I only handle Aurora Dynamics HR policy and operations questions — "
    "things like PTO, remote work, expenses, benefits, equipment, leave and "
    "workplace conduct. Ask me one of those and I'll look up the policy and "
    "cite it."
)


def access_token():
    """The configured access token, or "" for an open instance.

    APP_PASSWORD is the older name for the same secret. The deployment
    platform stores it under that name, and it rewrites its own env file on
    every deploy — so accepting both here is what stops the gate silently
    turning itself off after a redeploy.
    """
    return os.environ.get("APP_TOKEN") or os.environ.get("APP_PASSWORD") or ""


def _client_ip(request):
    """Real client address, behind the reverse proxy.

    X-Forwarded-For is appended to, so its FIRST entry is whatever the client
    sent — trusting it lets anyone reset their own rate limit by spoofing a
    header. The proxy's own X-Real-Ip is authoritative; failing that, the LAST
    XFF entry is the one our proxy added.
    """
    real = request.headers.get("x-real-ip", "").strip()
    if real:
        return real
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _rate_limited(ip, now):
    hits = _hits.setdefault(ip, deque())
    while hits and now - hits[0] > RATE_WINDOW:
        hits.popleft()
    if len(hits) >= RATE_LIMIT:
        return True
    hits.append(now)
    # keep the table from growing without bound on a long-lived process
    if len(_hits) > 1000:
        for stale in [k for k, v in _hits.items() if not v]:
            del _hits[stale]
    return False


def _expire_sessions(now):
    for sid, seen in list(_unlocked.items()):
        if now - seen > SESSION_TTL:
            del _unlocked[sid]
            sessions.pop(sid, None)



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
async def chat(req: ChatRequest, request: Request):
    sid = req.session_id or uuid.uuid4().hex[:12]
    now = time.time()
    _expire_sessions(now)

    def reply(answer, locked=None, status=200):
        body = {"session_id": sid, "answer": answer, "citations": [], "trace": []}
        if locked is not None:
            body["locked"] = locked
        return JSONResponse(body, status_code=status)

    # The correct token always gets through, even while rate limited —
    # otherwise a burst of traffic locks the legitimate user out of their own
    # instance. This is not a brute-force hole: a wrong guess still counts
    # against the limit below, so only someone who already has the token
    # benefits.
    token = access_token()
    unlocking = bool(token) and secrets.compare_digest(req.message.strip(), token)

    # Rate limit otherwise applies to locked sessions too, so the gate cannot
    # be used as a free guessing oracle.
    if not unlocking and _rate_limited(_client_ip(request), now):
        return reply(RATE_LIMITED_REPLY, status=429)

    if len(req.message) > MAX_MESSAGE_CHARS:
        return reply(TOO_LONG_REPLY)

    # Token gate, asked for in the conversation instead of by a login prompt.
    # The LLM is never called while a session is locked, which is the whole
    # point: an unauthorised visitor cannot spend the owner's API credit.
    if token:
        if sid not in _unlocked:
            if unlocking:
                _unlocked[sid] = now
                return reply(UNLOCKED_REPLY, locked=False)
            # A session id we have never seen is indistinguishable from one
            # that timed out, so say "expired" only for ids with history.
            return reply(EXPIRED_REPLY if sid in sessions else LOCKED_REPLY,
                         locked=True)
        _unlocked[sid] = now      # sliding window: activity keeps it alive

    # Checked in code, not left to the prompt: refuse before the model runs.
    if _BLOCKED.search(req.message):
        return reply(OFF_TOPIC_REPLY)

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
        "gated": bool(access_token()),
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
