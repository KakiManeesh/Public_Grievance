"""
resolver.py — Agent 4 (final) in the civic complaint pipeline.

Assigns each complaint to the correct government department, calculates its
SLA deadline, checks for breach, and assembles the final resolution ticket.
No LLM calls — pure routing and SLA logic using utils helpers.
"""

from utils import calculate_sla_deadline, format_resolution_ticket

# ---------------------------------------------------------------------------
# Fallback department used when a complaint's category has no entry in the
# departments dict (e.g. LLM returned an unexpected value).
# ---------------------------------------------------------------------------
_FALLBACK_DEPT: dict = {
    "department": "Unknown Department",
    "sla_hours":  {"High": 6, "Medium": 24, "Low": 72},
    "contact":    "support@ghmc.gov.in",
}


# ---------------------------------------------------------------------------
# Private helper
# ---------------------------------------------------------------------------

def _lookup_dept(category: str, departments: dict) -> dict:
    """Return the department entry for category, or a safe fallback if not found."""
    try:
        dept = departments.get(category)
        if isinstance(dept, dict) and dept:
            return dept
        return dict(_FALLBACK_DEPT)
    except Exception:
        return dict(_FALLBACK_DEPT)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve(complaints: list[dict], departments: dict) -> list[dict]:
    """Assign departments, calculate SLA deadlines, and return final resolution tickets for all complaints."""

    results: list[dict] = []

    for complaint in complaints:
        try:
            # ----------------------------------------------------------------
            # 1. Resolve department entry
            # ----------------------------------------------------------------
            try:
                category: str = str(complaint.get("category", ""))
            except Exception:
                category = ""

            dept: dict = _lookup_dept(category, departments)

            # ----------------------------------------------------------------
            # 2. Calculate SLA deadline
            #    calculate_sla_deadline() never raises — falls back to 72 h
            # ----------------------------------------------------------------
            try:
                priority:  str  = str(complaint.get("priority", "Medium"))
                timestamp       = complaint.get("timestamp")
                deadline        = calculate_sla_deadline(timestamp, priority, category, departments)
            except Exception:
                from datetime import datetime, timedelta
                deadline = datetime.now() + timedelta(hours=72)

            # ----------------------------------------------------------------
            # 3. Build resolution ticket
            #    format_resolution_ticket() never raises — has its own fallback
            # ----------------------------------------------------------------
            ticket: dict = format_resolution_ticket(complaint, dept, deadline)

            # ----------------------------------------------------------------
            # 3.5 Recalculate deterministic urgency_score
            # ----------------------------------------------------------------
            try:
                p = ticket.get("priority", "Medium")
                base_score = 8 if p == "High" else 2 if p == "Low" else 5
                
                if ticket.get("sla_breached"):
                    base_score += 2
                    
                loc_lower = str(ticket.get("location", "")).lower()
                if any(k in loc_lower for k in ["school", "hospital", "market"]):
                    base_score += 1
                    
                ticket["urgency_score"] = min(10, base_score)
            except Exception:
                pass

            # ----------------------------------------------------------------
            # 4. Inject cluster_id — not in helpers.format_resolution_ticket
            #    spec but required in the output schema for this agent
            # ----------------------------------------------------------------
            try:
                ticket["cluster_id"] = complaint.get("cluster_id", -1)
            except Exception:
                ticket["cluster_id"] = -1

        except Exception:
            # Last-resort: build a minimal safe ticket so no complaint is lost
            from datetime import datetime
            ticket = {
                "complaint_id":   complaint.get("id", "") if isinstance(complaint, dict) else "",
                "description":    complaint.get("description", "") if isinstance(complaint, dict) else "",
                "category":       complaint.get("category", "") if isinstance(complaint, dict) else "",
                "location":       complaint.get("location", "") if isinstance(complaint, dict) else "",
                "priority":       "Medium",
                "urgency_score":  0,
                "status":         "Open",
                "cluster_id":     -1,
                "department":     "Unknown Department",
                "contact":        "support@ghmc.gov.in",
                "reported_at":    datetime.now().isoformat(),
                "sla_deadline":   datetime.now().isoformat(),
                "sla_breached":   False,
                "time_remaining": "OVERDUE by 0h 0m",
            }

        results.append(ticket)

    # Guard: every complaint in → every ticket out
    if len(results) != len(complaints):
        raise ValueError(
            f"Silent row drop in resolve(): "
            f"{len(complaints)} complaints in, {len(results)} tickets out."
        )

    return results
