"""MCP tool discovery + real tool calls over stdio. No LLM key needed."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REQUIRED_TOOLS = {
    "search_policy_documents", "get_policy_section", "lookup_employee_profile",
    "check_pto_balance", "lookup_benefits_status", "create_mock_hr_ticket",
    "draft_hr_email",
}


async def _session_scope(fn):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "mcp_server.server"], cwd=str(ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)


def test_tool_discovery():
    async def check(session):
        listed = await session.list_tools()
        return {t.name for t in listed.tools}
    names = asyncio.run(_session_scope(check))
    assert REQUIRED_TOOLS <= names, f"missing: {REQUIRED_TOOLS - names}"


def test_tool_calls():
    async def check(session):
        pto = await session.call_tool("check_pto_balance", {"employee_id": "EMP003"})
        rag_hits = await session.call_tool(
            "search_policy_documents", {"query": "PTO manager approval notice", "k": 3})
        missing = await session.call_tool("check_pto_balance", {"employee_id": "EMP999"})
        return (pto.content[0].text, rag_hits.content[0].text, missing.content[0].text)

    pto_text, rag_text, missing_text = asyncio.run(_session_scope(check))
    assert json.loads(pto_text)["vacation_days_available"] == 2.5
    hits = json.loads(rag_text)
    assert any(h["doc_id"] == "POL-PTO-001" for h in hits)
    assert "EMP999" in missing_text and "valid employee ID" in missing_text
