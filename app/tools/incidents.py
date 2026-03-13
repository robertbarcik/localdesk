"""Incident management tool implementations."""

import json
import sqlite3
from datetime import datetime, timezone

from app.config import DATABASE_PATH


def _get_conn() -> sqlite3.Connection:
    return sqlite3.connect(DATABASE_PATH)


def create_incident(summary: str, priority: str, category: str, reporter_name: str) -> str:
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO incidents (summary, priority, category, reporter_name, status, created_at)
               VALUES (?, ?, ?, ?, 'open', ?)""",
            (summary, priority.lower(), category.lower(), reporter_name, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        ticket_id = f"INC-{cur.lastrowid:05d}"
        cur.execute("UPDATE incidents SET ticket_id = ? WHERE id = ?", (ticket_id, cur.lastrowid))
        conn.commit()
        return json.dumps(
            {
                "ticket_id": ticket_id,
                "summary": summary,
                "priority": priority.title(),
                "category": category.title(),
                "reporter": reporter_name,
                "status": "Open",
                "message": f"Incident {ticket_id} created successfully.",
            }
        )
    finally:
        conn.close()


def escalate_ticket(ticket_id: str, reason: str) -> str:
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, status FROM incidents WHERE ticket_id = ?", (ticket_id.upper(),))
        row = cur.fetchone()
        if not row:
            return json.dumps({"error": f"Ticket {ticket_id} not found."})
        if row[1] == "escalated":
            return json.dumps({"error": f"Ticket {ticket_id} is already escalated."})
        cur.execute(
            "UPDATE incidents SET status = 'escalated', escalation_reason = ?, escalated_at = ? WHERE ticket_id = ?",
            (reason, datetime.now(timezone.utc).isoformat(), ticket_id.upper()),
        )
        conn.commit()
        return json.dumps(
            {
                "ticket_id": ticket_id.upper(),
                "status": "Escalated",
                "reason": reason,
                "message": f"Ticket {ticket_id.upper()} has been escalated.",
            }
        )
    finally:
        conn.close()
