"""
helpers.py — Shared utility functions used across all agents in the pipeline.

No LLM calls, no API calls, no Flask. Pure stdlib (datetime, typing) only.
"""

from datetime import datetime, timedelta
from typing import Dict


# ---------------------------------------------------------------------------
# Priority normalization map (module-level constant for performance)
# ---------------------------------------------------------------------------

_PRIORITY_MAP: Dict[str, str] = {
    "urgent": "High",
    "critical": "High",
    "high": "High",
    "medium": "Medium",
    "normal": "Medium",
    "moderate": "Medium",
    "low": "Low",
    "minor": "Low",
}


# ---------------------------------------------------------------------------
# 1. parse_timestamp
# ---------------------------------------------------------------------------


def parse_timestamp(ts: str) -> datetime:
    """Parse a 'DD-MM-YY HH:MM' timestamp string, returning datetime.now() on failure."""
    try:
        return datetime.strptime(ts, "%d-%m-%y %H:%M")
    except (ValueError, TypeError):
        return datetime.now()


# ---------------------------------------------------------------------------
# 2. calculate_sla_deadline
# ---------------------------------------------------------------------------


def calculate_sla_deadline(
    timestamp: datetime,
    priority: str,
    category: str,
    departments: dict,
) -> datetime:
    """Add SLA hours (from departments config) to timestamp, defaulting to 72 h."""
    try:
        hours: int = departments[category]["sla_hours"][priority]
    except (KeyError, TypeError):
        hours = 72
    try:
        return timestamp + timedelta(hours=hours)
    except Exception:
        return datetime.now() + timedelta(hours=72)


# ---------------------------------------------------------------------------
# 3. is_sla_breached
# ---------------------------------------------------------------------------


def is_sla_breached(deadline: datetime) -> bool:
    """Return True if the current time has passed the given SLA deadline."""
    try:
        return datetime.now() > deadline
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 4. get_time_remaining
# ---------------------------------------------------------------------------


def get_time_remaining(deadline: datetime) -> str:
    """Return a human-readable string showing time remaining or overdue duration."""
    try:
        delta = deadline - datetime.now()
        total_minutes = int(abs(delta.total_seconds()) / 60)
        h, m = divmod(total_minutes, 60)

        if delta.total_seconds() >= 0:
            return f"{h}h {m}m remaining"
        else:
            return f"OVERDUE by {h}h {m}m"
    except Exception:
        return "OVERDUE by 0h 0m"


# ---------------------------------------------------------------------------
# 5. normalize_priority
# ---------------------------------------------------------------------------


def normalize_priority(raw: str) -> str:
    """Map an arbitrary priority string to exactly 'High', 'Medium', or 'Low'."""
    try:
        key = str(raw).strip().lower()
        return _PRIORITY_MAP.get(key, "Medium")
    except Exception:
        return "Medium"


# ---------------------------------------------------------------------------
# 6. get_urgency_band
# ---------------------------------------------------------------------------


def get_urgency_band(score: int) -> str:
    """Map a numeric urgency score (1-10) to 'High', 'Medium', or 'Low'."""
    try:
        score = int(score)
        if score >= 7:
            return "High"
        elif score >= 4:
            return "Medium"
        elif score >= 1:
            return "Low"
        else:
            return "Medium"
    except (ValueError, TypeError):
        return "Medium"


# ---------------------------------------------------------------------------
# 7. format_resolution_ticket
# ---------------------------------------------------------------------------


def format_resolution_ticket(
    complaint: dict,
    dept: dict,
    deadline: datetime,
) -> dict:
    """Assemble a complete resolution ticket dict from complaint, department, and deadline."""
    try:
        reported_at_raw = complaint.get("timestamp", datetime.now())
        # Accept both datetime objects and ISO strings
        if isinstance(reported_at_raw, datetime):
            reported_at_iso = reported_at_raw.isoformat()
        else:
            reported_at_iso = str(reported_at_raw)

        try:
            sla_deadline_iso: str = deadline.isoformat()
        except Exception:
            sla_deadline_iso = datetime.now().isoformat()

        try:
            is_overdue = is_sla_breached(deadline)
            try:
                delta = deadline - datetime.now()
                total_minutes = int(abs(delta.total_seconds()) / 60)
                if is_overdue:
                    overdue_minutes = total_minutes
                    remaining_minutes = None
                else:
                    overdue_minutes = None
                    remaining_minutes = total_minutes
            except Exception:
                overdue_minutes = None
                remaining_minutes = None

            return {
                "complaint_id": complaint.get("id", ""),
                "description": complaint.get("description", ""),
                "category": complaint.get("category", ""),
                "location": complaint.get("location", ""),
                "location_flagged": complaint.get("location_flagged", False),
                "flag_reason": complaint.get("flag_reason", ""),
                "priority": complaint.get("priority", "Medium"),
                "urgency_score": complaint.get("urgency_score", 0),
                "root_cause": complaint.get("root_cause", "Not analyzed"),
                "status": complaint.get("status", "Open"),
                "department": dept.get("department", ""),
                "contact": dept.get("contact", ""),
                "reported_at": reported_at_iso,
                "sla_deadline": sla_deadline_iso,
                "sla_breached": is_overdue,
                "time_remaining": get_time_remaining(deadline),
                "is_overdue": is_overdue,
                "overdue_minutes": overdue_minutes,
                "remaining_minutes": remaining_minutes,
            }
        except Exception:
            return {
                "is_overdue": False,
                "overdue_minutes": None,
                "remaining_minutes": None,
                "time_remaining": "Unknown",
            }
    except Exception:
        # Last-resort safe ticket — never crash the pipeline
        return {
            "complaint_id": complaint.get("id", "")
            if isinstance(complaint, dict)
            else "",
            "description": "",
            "category": "",
            "location": "",
            "priority": "Medium",
            "urgency_score": 0,
            "status": "Open",
            "department": "",
            "contact": "",
            "reported_at": datetime.now().isoformat(),
            "sla_deadline": datetime.now().isoformat(),
            "sla_breached": False,
            "time_remaining": "OVERDUE by 0h 0m",
            "is_overdue": False,
            "overdue_minutes": None,
            "remaining_minutes": None,
        }
