"""Aurora HR MCP server — exposes HR tools over MCP (stdio transport).

Run: python -m mcp_server.server   (from the repo root)

Tools:
  search_policy_documents  – semantic search over the policy RAG index
  get_policy_section       – fetch full sections of one policy document
  lookup_employee_profile  – mock employee directory
  check_pto_balance        – mock PTO balances
  lookup_benefits_status   – mock benefits elections/eligibility
  create_mock_hr_ticket    – MOCK action: writes a ticket to a local JSON file
  draft_hr_email           – MOCK action: returns a draft, sends nothing
"""
import json
import sys
from pathlib import Path

from mcp.server import MCPServer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import rag  # noqa: E402

MOCK = ROOT / "mock_data"
TICKETS = MOCK / "tickets.json"

mcp = MCPServer("aurora-hr")


def _load(name):
    return json.loads((MOCK / name).read_text(encoding="utf-8"))


@mcp.tool()
def search_policy_documents(query: str, k: int = 5) -> str:
    """Semantic search over Aurora Dynamics policy documents. Returns the top-k
    most relevant policy sections with doc_id, title, section and snippet —
    use these fields to cite sources in your answer."""
    return json.dumps(rag.search(query, k=k), indent=1)


@mcp.tool()
def get_policy_section(doc_id: str, section_query: str = "") -> str:
    """Fetch the full text of sections of one policy document by its doc_id
    (e.g. POL-PTO-001). Optional section_query filters sections by name."""
    out = rag.get_section(doc_id, section_query)
    return json.dumps(out, indent=1) if out else f"No document found with doc_id {doc_id!r}."


@mcp.tool()
def lookup_employee_profile(employee_id: str) -> str:
    """Look up a (mock) employee profile by employee_id (e.g. EMP003) or by
    name. Returns role, department, manager, location, employment type and
    work model."""
    employees = _load("employees.json")
    q = employee_id.strip().lower()
    for e in employees:
        if e["employee_id"].lower() == q or q in e["name"].lower():
            return json.dumps(e, indent=1)
    return (f"No employee found for {employee_id!r}. "
            "Ask the user for a valid employee ID (format EMP###).")


@mcp.tool()
def check_pto_balance(employee_id: str) -> str:
    """Check a (mock) employee's PTO balances: vacation, sick days, floating
    holidays, accrual rate and pending requests."""
    balances = _load("pto_balances.json")
    rec = balances.get(employee_id.strip().upper())
    if not rec:
        return (f"No PTO record for {employee_id!r}. "
                "Ask the user for a valid employee ID (format EMP###).")
    return json.dumps(rec, indent=1)


@mcp.tool()
def lookup_benefits_status(employee_id: str) -> str:
    """Check a (mock) employee's benefits eligibility and current elections
    (medical, dental, vision, 401k)."""
    benefits = _load("benefits.json")
    rec = benefits.get(employee_id.strip().upper())
    if not rec:
        return (f"No benefits record for {employee_id!r}. "
                "Ask the user for a valid employee ID (format EMP###).")
    return json.dumps(rec, indent=1)


@mcp.tool()
def create_mock_hr_ticket(employee_id: str, category: str, summary: str,
                          details: str = "") -> str:
    """MOCK ACTION — create an HR ticket in a local file. Nothing real is
    filed. Only call this after the user has explicitly confirmed they want
    the ticket created. Categories: pto, benefits, remote_work, expenses,
    equipment, conduct, other."""
    tickets = json.loads(TICKETS.read_text(encoding="utf-8")) if TICKETS.exists() else []
    ticket = {
        "ticket_id": f"TICKET-{1001 + len(tickets)}",
        "employee_id": employee_id.strip().upper(),
        "category": category,
        "summary": summary,
        "details": details,
        "status": "open (mock)",
    }
    tickets.append(ticket)
    TICKETS.write_text(json.dumps(tickets, indent=1), encoding="utf-8")
    return json.dumps({"created": True, "mock": True, **ticket}, indent=1)


@mcp.tool()
def draft_hr_email(recipient: str, subject: str, key_points: str) -> str:
    """MOCK ACTION — draft (but never send) an email, e.g. to a manager or
    People Operations. Returns the draft text for the user to review and send
    themselves. key_points: what the email needs to say, as plain text."""
    body = (f"To: {recipient}\nSubject: {subject}\n\n"
            f"Hi,\n\n{key_points.strip()}\n\nBest regards")
    return json.dumps({"draft": body, "sent": False,
                       "note": "Draft only — review and send it yourself."}, indent=1)


if __name__ == "__main__":
    rag.ingest()          # build the index once, inside the tool process
    mcp.run()             # stdio transport
