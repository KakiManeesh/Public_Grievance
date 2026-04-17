"""Flask API for Hyderabad civic complaint management."""

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta
from uuid import uuid4

import firebase_admin
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


def _get_all_complaints(limit: int = 500):
    return [
        doc.to_dict()
        for doc in db.collection("complaints")
        .order_by("reported_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .stream()
    ]


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"})


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

    classified = classify([raw_complaint])
    ticket = resolve(classified, departments)[0]
    ticket["reporter"] = reporter
    ticket["status"] = ticket.get("status", "Open")
    ticket["reported_at"] = ticket.get("reported_at") or reported_at

    cutoff = datetime.utcnow() - timedelta(days=30)
    ticket_category = str(ticket.get("category", "")).strip()

    similar_ids = []
    similar_count = 0
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

    priority_boosted = False
    boost_reason = ""
    current_priority = str(ticket.get("priority", "Medium"))
    current_urgency = int(ticket.get("urgency_score", 5))

    if similar_count >= 3:
        ticket["priority"] = "High"
        ticket["urgency_score"] = min(current_urgency + 2, 10)
        priority_boosted = True
        boost_reason = (
            f"Escalated: {similar_count} similar complaints reported in last 30 days"
        )
    elif similar_count >= 2 and current_priority == "Low":
        ticket["priority"] = "Medium"
        priority_boosted = True
        boost_reason = (
            f"Upgraded: {similar_count} similar complaints in last 30 days"
        )

    ticket["similar_count"] = similar_count
    ticket["similar_ids"] = similar_ids
    ticket["priority_boosted"] = priority_boosted
    ticket["boost_reason"] = boost_reason

    db.collection("complaints").document(ticket["complaint_id"]).set(ticket)
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
