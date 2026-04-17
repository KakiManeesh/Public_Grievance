"""Flask API for Hyderabad civic complaint management."""

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta
from uuid import uuid4

import firebase_admin
import groq
import requests
from dotenv import load_dotenv
from firebase_admin import credentials, firestore
from flask import Flask, jsonify, request
from flask_cors import CORS

from agents import classify, resolve

load_dotenv()

app = Flask(__name__)
CORS(app)


def _safe_iso_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def _priority_rank(priority: str) -> int:
    mapping = {"Low": 0, "Medium": 1, "High": 2}
    return mapping.get(str(priority), 1)


def _rank_to_priority(rank: int) -> str:
    mapping = {0: "Low", 1: "Medium", 2: "High"}
    return mapping.get(max(0, min(2, rank)), "Medium")


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except Exception:
        return None


def _load_departments() -> dict:
    base_dir = os.path.dirname(__file__)
    departments_path = os.path.join(base_dir, "data", "departments.json")
    try:
        with open(departments_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        app.logger.error("Failed to load departments: %s", exc)
        return {}


departments = _load_departments()

if not firebase_admin._apps:
    key_path = os.path.join(os.path.dirname(__file__), "serviceAccountKey.json")
    cred = credentials.Certificate(key_path)
    firebase_admin.initialize_app(cred)

db = firestore.client()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
_GEOCODE_CACHE: dict[str, dict[str, float]] = {}


def _get_all_complaints(limit: int = 500):
    return [
        doc.to_dict()
        for doc in db.collection("complaints")
        .order_by("reported_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .stream()
    ]


def _load_hyd_locality_centers() -> list[dict]:
    path = os.path.join(os.path.dirname(__file__), "hyd_lat_lan.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception as exc:
        app.logger.error("Failed to load hyd_lat_lan.json: %s", exc)
    return []


def _normalize_locality(location: str) -> str:
    text = re.sub(r"[^a-z0-9\s]", " ", str(location or "").lower()).strip()
    text = re.sub(r"\s+", " ", text)
    prefixes = ("near ", "opp ", "opposite ", "beside ", "in ")
    for prefix in prefixes:
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    return text


def _extract_locality_token(location: str) -> str:
    normalized = _normalize_locality(location)
    if not normalized:
        return "unknown"
    parts = normalized.split()
    return " ".join(parts[:2]) if len(parts) > 1 else parts[0]


def _forward_geocode_hyderabad(location: str) -> tuple[float | None, float | None]:
    token = _extract_locality_token(location)
    if token in _GEOCODE_CACHE:
        cached = _GEOCODE_CACHE[token]
        return cached.get("lat"), cached.get("lng")
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": f"{location}, Hyderabad, Telangana, India",
                "format": "json",
                "limit": 1,
            },
            headers={"User-Agent": "CivicPulseHyd/1.0"},
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()
        if not data:
            return None, None
        lat = float(data[0]["lat"])
        lng = float(data[0]["lon"])
        _GEOCODE_CACHE[token] = {"lat": lat, "lng": lng}
        return lat, lng
    except Exception:
        return None, None


def _groq_generate_json(prompt: str) -> dict:
    if not GROQ_API_KEY:
        return {}
    try:
        client = groq.Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            messages=[
                {
                    "role": "system",
                    "content": "Return valid JSON only. No markdown fences or extra text.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )
        text = response.choices[0].message.content.strip() if response.choices else ""
        if text.startswith("```"):
            text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text) if text else {}
    except Exception:
        return {}


def _groq_validate_complaint(description: str, location: str) -> tuple[bool, str]:
    if not GROQ_API_KEY:
        return True, ""
    prompt = (
        "Is this a legitimate civic complaint?\n"
        f"Description: {description}\n"
        f"Location: {location}\n"
        "Rules:\n"
        '- Mark INVALID only if clearly fake, spam, gibberish, or abusive (e.g. "asdfgh", "test123", "Modi is bad")\n'
        "- Real complaints with exaggeration or emotion are still VALID\n"
        "- Be lenient — only reject obvious non-complaints\n"
        'Respond ONLY in JSON: {"is_valid": true/false, "reason": "..."}'
    )
    parsed = _groq_generate_json(prompt)
    if not parsed:
        return True, ""
    is_valid = bool(parsed.get("is_valid", True))
    reason = str(parsed.get("reason", "")).strip()
    return is_valid, reason


def _compact_for_pattern(item: dict) -> dict:
    return {
        "complaint_id": item.get("complaint_id"),
        "category": item.get("category"),
        "locality": item.get("locality"),
        "location": item.get("location"),
        "reported_at": item.get("reported_at"),
        "priority": item.get("priority"),
        "urgency_score": item.get("urgency_score"),
        "description": str(item.get("description", ""))[:150],
    }


def _format_complaints_for_prompt(complaints: list[dict]) -> str:
    if not complaints:
        return "None"
    lines = []
    for item in complaints:
        lines.append(
            "- "
            + json.dumps(
                {
                    "complaint_id": item.get("complaint_id"),
                    "description": item.get("description"),
                    "category": item.get("category"),
                    "location": item.get("location"),
                    "locality": item.get("locality"),
                    "timestamp": item.get("reported_at") or item.get("timestamp"),
                },
                ensure_ascii=True,
            )
        )
    return "\n".join(lines)


def _empty_pattern_analysis() -> dict:
    return {
        "emergency_spike": False,
        "spike_details": "",
        "locality_pattern_detected": False,
        "locality_pattern": {
            "summary": "",
            "root_cause": "",
            "complaints_involved": [],
            "severity": "",
            "recommendation": "",
        },
        "citywide_pattern_detected": False,
        "citywide_pattern": {
            "summary": "",
            "localities_affected": [],
            "severity": "",
            "recommendation": "",
        },
    }


def _normalize_severity(value: str) -> str:
    allowed = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    normalized = str(value or "").strip().upper()
    return normalized if normalized in allowed else ""


def _normalize_string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _run_pattern_analysis(new_ticket: dict) -> dict:
    category = str(new_ticket.get("category", "")).strip()
    location = str(new_ticket.get("location", "")).strip()
    locality = _extract_locality_token(location)
    timestamp = str(new_ticket.get("reported_at") or new_ticket.get("timestamp") or _safe_iso_now())
    complaint_id = str(new_ticket.get("complaint_id", "")).strip()
    cutoff = datetime.utcnow() - timedelta(days=30)
    docs = db.collection("complaints").stream()

    same_locality = []
    same_category_other_localities = []
    for doc in docs:
        item = doc.to_dict()
        item_id = str(item.get("complaint_id") or doc.id)
        if complaint_id and item_id == complaint_id:
            continue
        item_dt = _parse_iso_datetime(item.get("reported_at") or item.get("timestamp"))
        if not item_dt or item_dt < cutoff:
            continue
        item_locality = _extract_locality_token(item.get("location", ""))
        item_category = str(item.get("category", "")).strip()
        compact_item = _compact_for_pattern(item)
        if item_locality == locality:
            same_locality.append(compact_item)
        if item_category == category and item_locality != locality:
            same_category_other_localities.append(compact_item)

    locality_complaints = _format_complaints_for_prompt(same_locality[:150])
    similar_complaints = _format_complaints_for_prompt(same_category_other_localities[:150])

    prompt = f"""You are an expert civic intelligence analyst working for a smart city operations center.

A new complaint has just been registered:

text
Description: {new_ticket.get("description", "")}
Category: {category}
Location: {location}
Time: {timestamp}
Context — All complaints from the same locality (last 30 days):

text
{locality_complaints}
Context — Similar complaints from other localities (last 30 days):

text
{similar_complaints}
Your job is to think in three layers:

Layer 1 — Emergency Spike Detection:

Are there 3+ complaints from the same locality within the last 24 hours?

If yes, flag as emergency spike regardless of category

Even if a spike exists, continue evaluating Layer 2 and Layer 3 independently

Layer 2 — Locality Pattern (same area, any category):

Look for thematic clusters, NOT just category matches

Connected complaint chains must be recognized:
Sewage leak → Bad smell → Rats → Health complaints = Sanitation/Health Crisis

Potholes → Waterlogging → Road damage = Drainage/Infrastructure failure

Power cuts → Street lights out → Transformer issues = Electrical failure


A pattern requires: 3+ complaints, spread across 2+ different days, pointing to a common root cause

Layer 3 — Citywide Pattern (same issue, multiple localities):

Is the same type of problem appearing in multiple different localities?

This may indicate a systemic city-level failure (e.g. garbage collection breakdown citywide)

Requires: same theme in 3+ different localities within 14 days

Strict Rules:

Only report a pattern if you are highly confident — do not guess

Complaints within the same 24 hours should trigger spike escalation, but can still contribute to broader trend confidence when evidence across days/localities is strong

Different categories CAN form a pattern if semantically connected

If nothing significant found, say so clearly — do not hallucinate patterns

Severity of pattern: LOW (informational), MEDIUM (needs scheduled action), HIGH (needs urgent intervention), CRITICAL (immediate escalation required)

Respond ONLY in this JSON format:

json
{{
  "emergency_spike": true/false,
  "spike_details": "...",
  "locality_pattern_detected": true/false,
  "locality_pattern": {{
    "summary": "...",
    "root_cause": "...",
    "complaints_involved": [...],
    "severity": "LOW/MEDIUM/HIGH/CRITICAL",
    "recommendation": "..."
  }},
  "citywide_pattern_detected": true/false,
  "citywide_pattern": {{
    "summary": "...",
    "localities_affected": [...],
    "severity": "LOW/MEDIUM/HIGH/CRITICAL",
    "recommendation": "..."
  }}
}}"""

    parsed = _groq_generate_json(prompt)
    if not isinstance(parsed, dict):
        return _empty_pattern_analysis()

    result = _empty_pattern_analysis()
    result["emergency_spike"] = bool(parsed.get("emergency_spike", False))
    result["spike_details"] = str(parsed.get("spike_details", "")).strip()
    result["locality_pattern_detected"] = bool(
        parsed.get("locality_pattern_detected", False)
    )
    result["citywide_pattern_detected"] = bool(
        parsed.get("citywide_pattern_detected", False)
    )

    locality_pattern = parsed.get("locality_pattern", {})
    if isinstance(locality_pattern, dict):
        result["locality_pattern"] = {
            "summary": str(locality_pattern.get("summary", "")).strip(),
            "root_cause": str(locality_pattern.get("root_cause", "")).strip(),
            "complaints_involved": _normalize_string_list(
                locality_pattern.get("complaints_involved", [])
            ),
            "severity": _normalize_severity(locality_pattern.get("severity", "")),
            "recommendation": str(locality_pattern.get("recommendation", "")).strip(),
        }

    citywide_pattern = parsed.get("citywide_pattern", {})
    if isinstance(citywide_pattern, dict):
        result["citywide_pattern"] = {
            "summary": str(citywide_pattern.get("summary", "")).strip(),
            "localities_affected": _normalize_string_list(
                citywide_pattern.get("localities_affected", [])
            ),
            "severity": _normalize_severity(citywide_pattern.get("severity", "")),
            "recommendation": str(citywide_pattern.get("recommendation", "")).strip(),
        }

    return result


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"})


@app.route("/api/hyd-locations", methods=["GET"])
def get_hyd_locations():
    return jsonify(_load_hyd_locality_centers())


@app.route("/api/complaints", methods=["POST"])
def create_complaint():
    payload = request.get_json(silent=True) or {}
    description = str(payload.get("description", "")).strip()
    location = str(payload.get("location", "")).strip()
    reporter = str(payload.get("reporter", "")).strip()

    if not description or not location:
        return (
            jsonify({"error": "description and location are required"}),
            400,
        )

    legit_ok, legit_reason = _groq_validate_complaint(description, location)
    if not legit_ok:
        return (
            jsonify(
                {
                    "error": "invalid_complaint",
                    "reason": legit_reason
                    or "This does not appear to be a valid civic complaint.",
                }
            ),
            400,
        )

    complaint_id = str(uuid4())[:8]
    reported_at = _safe_iso_now()
    raw_complaint = {
        "id": complaint_id,
        "complaint_id": complaint_id,
        "description": description,
        "location": location,
        "reporter": reporter,
        "timestamp": reported_at,
        "reported_at": reported_at,
        "status": "Open",
    }
    lat, lng = _forward_geocode_hyderabad(location)
    locality_token = _extract_locality_token(location)
    raw_complaint["lat"] = lat
    raw_complaint["lng"] = lng
    raw_complaint["locality"] = locality_token

    classified = classify([raw_complaint])
    ticket = resolve(classified, departments)[0]
    ticket["reporter"] = reporter
    ticket["status"] = ticket.get("status", "Open")
    ticket["reported_at"] = ticket.get("reported_at") or reported_at
    ticket["lat"] = ticket.get("lat", lat)
    ticket["lng"] = ticket.get("lng", lng)
    ticket["locality"] = ticket.get("locality") or locality_token

    cutoff = datetime.utcnow() - timedelta(days=30)
    locality_cutoff = datetime.utcnow() - timedelta(days=7)
    ticket_category = str(ticket.get("category", "")).strip()
    ticket_locality = _extract_locality_token(ticket.get("location", ""))

    similar_ids = []
    similar_count = 0
    locality_type_count_7d = 0
    if ticket_category:
        similar_docs = (
            db.collection("complaints")
            .where("category", "==", ticket_category)
            .stream()
        )
        for doc in similar_docs:
            existing = doc.to_dict()
            existing_dt = _parse_iso_datetime(existing.get("reported_at"))
            if existing_dt and existing_dt >= cutoff:
                similar_count += 1
                existing_id = existing.get("complaint_id") or doc.id
                similar_ids.append(existing_id)
            existing_locality = _extract_locality_token(existing.get("location", ""))
            if existing_locality == ticket_locality and existing_dt and existing_dt >= locality_cutoff:
                locality_type_count_7d += 1

    priority_boosted = False
    boost_reason = ""
    base_priority = str(ticket.get("priority", "Medium"))
    current_priority = base_priority
    base_urgency = int(ticket.get("urgency_score", 5))
    current_urgency = base_urgency

    # Strict boost rule:
    # - only if 3+ same category in same locality within 7 days
    # - boost by only one level
    # - trivial complaints (urgency<4) cannot be boosted to High
    if locality_type_count_7d >= 3:
        boosted_rank = _priority_rank(base_priority) + 1
        if base_urgency < 4:
            boosted_rank = min(boosted_rank, 1)  # cap to Medium for trivial complaints
        ticket["priority"] = _rank_to_priority(boosted_rank)
        if ticket["priority"] != base_priority:
            ticket["urgency_score"] = min(current_urgency + 1, 10)
            priority_boosted = True
            boost_reason = (
                f"Upgraded: {locality_type_count_7d} similar {ticket_category} complaints "
                f"in {ticket_locality} in last 7 days"
            )

    ticket["similar_count"] = similar_count
    ticket["similar_ids"] = similar_ids
    ticket["base_priority"] = base_priority
    ticket["base_urgency_score"] = base_urgency
    ticket["locality_type_count_7d"] = locality_type_count_7d
    ticket["priority_boosted"] = priority_boosted
    ticket["boost_reason"] = boost_reason
    db.collection("complaints").document(ticket["complaint_id"]).set(ticket)
    pattern_result = _run_pattern_analysis(ticket)
    ticket["pattern_analysis"] = pattern_result
    db.collection("complaints").document(ticket["complaint_id"]).set(
        {"pattern_analysis": pattern_result},
        merge=True,
    )
    return jsonify(ticket), 201


@app.route("/api/complaints", methods=["GET"])
def get_complaints():
    complaints = [
        doc.to_dict()
        for doc in db.collection("complaints")
        .order_by("reported_at", direction=firestore.Query.DESCENDING)
        .limit(200)
        .stream()
    ]
    return jsonify(complaints)


@app.route("/api/complaints/<complaint_id>", methods=["GET"])
def get_complaint_by_id(complaint_id: str):
    doc = db.collection("complaints").document(complaint_id).get()
    if not doc.exists:
        return jsonify({"error": "Complaint not found"}), 404
    return jsonify(doc.to_dict())


@app.route("/api/clusters", methods=["GET"])
def get_clusters():
    return jsonify([])


@app.route("/api/stats", methods=["GET"])
def get_stats():
    complaints = _get_all_complaints(limit=500)
    total = len(complaints)
    by_category = defaultdict(int)
    by_priority = {"High": 0, "Medium": 0, "Low": 0}
    by_status = defaultdict(int)
    sla_breached_count = 0
    priority_boosted_count = 0
    flagged_locations = 0
    resolved_count = 0

    for ticket in complaints:
        cat = str(ticket.get("category", "Unknown"))
        by_category[cat] += 1

        pri = str(ticket.get("priority", "Medium"))
        if pri in by_priority:
            by_priority[pri] += 1

        status = str(ticket.get("status", "Unknown"))
        by_status[status] += 1
        if status.lower() == "resolved":
            resolved_count += 1

        if ticket.get("sla_breached") is True:
            sla_breached_count += 1
        if ticket.get("priority_boosted") is True:
            priority_boosted_count += 1
        if ticket.get("location_flagged") is True:
            flagged_locations += 1

    stats = {
        "total": total,
        "by_category": dict(by_category),
        "by_priority": by_priority,
        "by_status": dict(by_status),
        "sla_breached": sla_breached_count,
        "resolved": resolved_count,
        "flagged_locations": flagged_locations,
        "priority_boosted": priority_boosted_count,
        "high_priority": by_priority["High"],
    }
    return jsonify(stats)


@app.route("/api/breached", methods=["GET"])
def get_breached():
    breached_docs = (
        db.collection("complaints").where("sla_breached", "==", True).stream()
    )
    return jsonify([doc.to_dict() for doc in breached_docs])


@app.route("/api/refresh", methods=["POST", "GET"])
def refresh_cache():
    return jsonify(
        {
            "status": "success",
            "message": "Realtime mode enabled. No cache refresh needed.",
        }
    )


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", 5000))
    app.run(host="0.0.0.0", port=port)
