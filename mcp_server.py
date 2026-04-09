"""MCP server exposing LocalDesk IT service desk tools via FastMCP."""

import json
import sqlite3
import sys
from pathlib import Path

# Ensure app package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.fastmcp import FastMCP

from app.config import DATABASE_PATH
from app.tools import assets, incidents, knowledge, sla

mcp = FastMCP(
    "localdesk",
    instructions=(
        "LocalDesk IT Service Desk. Tools for managing incidents, "
        "looking up SLAs and assets, searching the knowledge base, "
        "and viewing a dashboard summary."
    ),
)


@mcp.tool()
def check_sla(customer_tier: str, priority: str) -> str:
    """Look up contractual SLA response and resolution times for a given customer tier (gold/silver/bronze) and priority level (critical/high/medium/low)."""
    return sla.check_sla(customer_tier=customer_tier, priority=priority)


@mcp.tool()
def create_incident(summary: str, priority: str, category: str, reporter_name: str) -> str:
    """Create a new incident ticket. Priority: critical/high/medium/low. Category: network/hardware/software/access/other."""
    return incidents.create_incident(
        summary=summary, priority=priority, category=category, reporter_name=reporter_name
    )


@mcp.tool()
def lookup_asset(employee_id: str) -> str:
    """Look up hardware and software assets assigned to an employee by their employee ID (e.g. EMP-001)."""
    return assets.lookup_asset(employee_id=employee_id)


@mcp.tool()
def escalate_ticket(ticket_id: str, reason: str) -> str:
    """Escalate an existing incident ticket. Updates its status to escalated and logs the reason."""
    return incidents.escalate_ticket(ticket_id=ticket_id, reason=reason)


@mcp.tool()
def search_kb(query: str) -> str:
    """Search the knowledge base for relevant articles, troubleshooting steps, policies, and procedures."""
    try:
        return knowledge.search_kb(query=query)
    except Exception as e:
        return json.dumps({"error": f"Knowledge base unavailable: {e}"})


@mcp.tool()
def get_dashboard_summary() -> str:
    """Get a summary of all incidents — counts by status, by priority, and the 5 most recent tickets."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        total = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]

        by_status = {}
        for row in conn.execute("SELECT status, COUNT(*) AS cnt FROM incidents GROUP BY status"):
            by_status[row["status"]] = row["cnt"]

        by_priority = {}
        for row in conn.execute("SELECT priority, COUNT(*) AS cnt FROM incidents GROUP BY priority"):
            by_priority[row["priority"]] = row["cnt"]

        recent = []
        for row in conn.execute(
            "SELECT ticket_id, summary, priority, status, created_at "
            "FROM incidents ORDER BY created_at DESC LIMIT 5"
        ):
            recent.append(dict(row))
    finally:
        conn.close()

    lines = [f"=== Dashboard Summary ({total} total incidents) ===", ""]

    lines.append("By Status:")
    for status, count in by_status.items():
        lines.append(f"  {status}: {count}")

    lines.append("")
    lines.append("By Priority:")
    for priority, count in by_priority.items():
        lines.append(f"  {priority}: {count}")

    if recent:
        lines.append("")
        lines.append("Recent Incidents:")
        for r in recent:
            lines.append(f"  [{r['ticket_id']}] {r['summary']} ({r['priority']}, {r['status']})")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
