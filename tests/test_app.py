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


def test_password_gate(monkeypatch):
    """APP_PASSWORD set -> / and /chat need Basic auth; /health stays open."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-used")
    monkeypatch.setenv("APP_PASSWORD", "s3cret")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200      # public
        assert client.get("/").status_code == 401            # gated
        assert client.post("/chat", json={"message": "hi"}).status_code == 401
        assert client.get("/", auth=("grader", "wrong")).status_code == 401
        assert client.get("/", auth=("grader", "s3cret")).status_code == 200
