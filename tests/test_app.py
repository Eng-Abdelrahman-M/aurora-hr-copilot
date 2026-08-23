"""App start + RAG smoke tests. No LLM key needed."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_rag_index_and_search():
    from app import rag
    n = rag.ingest()
    assert n >= 30, f"expected 30+ chunks, got {n}"
    hits = rag.search("how many vacation days carry over into next year", k=3)
    assert hits and hits[0]["doc_id"] == "POL-PTO-001"
    assert {"doc_id", "title", "section", "snippet"} <= set(hits[0])


def test_app_starts_and_health(monkeypatch):
    """The app boots, connects to the MCP server, and /health reports it."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-used-by-health")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:          # runs lifespan → real MCP subprocess
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["mcp_connected"] is True
        assert len(body["mcp_tools"]) >= 5

        r = client.get("/")
        assert r.status_code == 200
        assert "Aurora HR Copilot" in r.text


def test_chat_token_gate(monkeypatch):
    """APP_TOKEN set -> the assistant asks for the token and refuses to answer
    (and never calls the LLM) until the right one is pasted into the chat."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-used")
    monkeypatch.setenv("APP_TOKEN", "s3cret-token")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        assert client.get("/").status_code == 200          # page is public
        health = client.get("/health").json()
        assert health["gated"] is True

        # a normal question while locked: asked for the token, no LLM call
        r = client.post("/chat", json={"message": "How many PTO days do I get?"})
        assert r.status_code == 200
        body = r.json()
        sid = body["session_id"]
        assert body["locked"] is True
        assert "access token" in body["answer"].lower()
        assert body["trace"] == [] and body["citations"] == []

        # wrong token stays locked
        wrong = client.post("/chat", json={"message": "hunter2", "session_id": sid}).json()
        assert wrong["locked"] is True

        # right token unlocks that session
        ok = client.post("/chat", json={"message": "s3cret-token", "session_id": sid}).json()
        assert ok["locked"] is False
        assert "access granted" in ok["answer"].lower()
