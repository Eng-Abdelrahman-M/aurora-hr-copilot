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


def _find_employee(who):
    """Resolve an employee_id OR a name (full, first, or last) to a record.

    Every people-data tool goes through this, so users can say "Abdelrahman"
    anywhere an ID is accepted instead of only in lookup_employee_profile.
    """
    q = (who or "").strip().lower()
    if not q:
        return None
    for e in _load("employees.json"):
        name = e["name"].lower()
        if q == e["employee_id"].lower() or q == name:
            return e
        # first/last name, or any full-word part of the name
        if q in name.split() or (len(q) > 2 and q in name):
            return e
    return None


def _not_found(who, kind):
    return (f"No {kind} found for {who!r}. Ask the user for their name as it "
            "appears in the directory, or an employee ID (format EMP###).")


@mcp.tool()
def search_policy_documents(query: str, k: int = 8) -> str:
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
def lookup_employee_profile(employee: str) -> str:
    """Look up a (mock) employee profile by name (e.g. "Abdelrahman Othman",
    or just "Abdelrahman") or by employee_id (e.g. EMP003). Returns role,
    department, manager, location, employment type and work model."""
    e = _find_employee(employee)
    return json.dumps(e, indent=1) if e else _not_found(employee, "employee")


@mcp.tool()
def check_pto_balance(employee: str) -> str:
    """Check a (mock) employee's PTO balances: vacation, sick days, floating
    holidays, accrual rate and pending requests. Accepts a name or an
    employee_id."""
    e = _find_employee(employee)
    if not e:
        return _not_found(employee, "employee")
    rec = _load("pto_balances.json").get(e["employee_id"])
    if not rec:
        return _not_found(employee, "PTO record")
    return json.dumps({"employee_id": e["employee_id"], "name": e["name"], **rec}, indent=1)


@mcp.tool()
def lookup_benefits_status(employee: str) -> str:
    """Check a (mock) employee's benefits eligibility and current elections
    (medical, dental, vision, 401k). Accepts a name or an employee_id."""
    e = _find_employee(employee)
    if not e:
        return _not_found(employee, "employee")
    rec = _load("benefits.json").get(e["employee_id"])
    if not rec:
        return _not_found(employee, "benefits record")
    return json.dumps({"employee_id": e["employee_id"], "name": e["name"], **rec}, indent=1)


@mcp.tool()
def create_mock_hr_ticket(employee_id: str, category: str, summary: str,
                          details: str = "") -> str:
    """MOCK ACTION — create an HR ticket in a local file. Nothing real is
    filed. Only call this after the user has explicitly confirmed they want
    the ticket created. Categories: pto, benefits, remote_work, expenses,
    equipment, conduct, other."""
    tickets = json.loads(TICKETS.read_text(encoding="utf-8")) if TICKETS.exists() else []
    e = _find_employee(employee_id)
    ticket = {
        "ticket_id": f"TICKET-{1001 + len(tickets)}",
        "employee_id": e["employee_id"] if e else employee_id.strip().upper(),
        "employee_name": e["name"] if e else None,
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
