"""
classifier.py — Agent 2 in the civic complaint pipeline.

Derives category, priority, urgency_score, and reason for each complaint
using a hybrid Algorithm + LLM approach. The algorithm runs first and
handles high-confidence cases; the LLM is invoked only for ambiguous ones.
"""

import json
import os
import random

from dotenv import load_dotenv
from dotenv import load_dotenv
import groq

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_CATEGORIES: list[str] = [
    "Roads",
    "Sanitation",
    "Water",
    "Electricity",
    "Traffic",
    "Safety",
    "Public Property",
    "Health",
    "Parks",
    "Noise",
    "Other",
]

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Roads": [
        "pothole",
        "road",
        "gravel",
        "pavement",
        "asphalt",
        "divider",
        "crater",
        "tar",
    ],
    "Sanitation": [
        "garbage",
        "waste",
        "trash",
        "dump",
        "litter",
        "bins",
        "burning",
        "smell",
    ],
    "Water": [
        "water",
        "pipe",
        "leak",
        "supply",
        "sewage",
        "overflow",
        "tap",
        "drainage",
    ],
    "Electricity": [
        "light",
        "power",
        "electric",
        "wire",
        "transformer",
        "outage",
        "voltage",  # ← add
        "streetlight",
        "pole",
        "sparking",
    ],
    "Safety": [
        "crime",
        "theft",
        "assault",
        "unsafe",
        "police",
        "threat",
        "robbery",
        "harassment",
        "suspicious",
        "attack",
    ],
    "Traffic": [
        "signal",
        "traffic",
        "congestion",
        "zebra",
        "speed",
        "marking",
        "junction",
        "parking",
        "diversion",
    ],
    "Health": [
        "health",
        "disease",
        "mosquito",
        "clinic",
        "fever",
    ],
    "Parks": [
        "park",
        "garden",
        "tree",
        "playground",
        "bench",
    ],
    "Noise": [
        "noise",
        "loud",
        "speaker",
        "dj",
        "sound",
    ],
}

SEVERITY_KEYWORDS: list[str] = [
    "accident",
    "injury",
    "collapse",
    "hazard",
    "school",
    "hospital",
    "fire",
    "danger",
    "child",
]

# Words that elevate / deflate priority in the absence of a severity keyword
_HIGH_TONE_WORDS: list[str] = [
    "urgent",
    "emergency",
    "critical",
    "severe",
    "immediately",
    "badly",
    "serious",
    "major",
    "extreme",
]
_LOW_TONE_WORDS: list[str] = [
    "minor",
    "small",
    "little",
    "slight",
    "barely",
    "cosmetic",
    "negligible",
]

# LLM prompt — kept as a module-level constant so it is built once
_PROMPT_TEMPLATE: str = (
    "You are a civic complaint classifier for Hyderabad municipal services.\n"
    "Analyze the complaint and return a JSON object with exactly these fields:\n"
    "- category: one of [Roads, Sanitation, Water, Electricity, Traffic, Safety, Public Property, Health, Parks, Noise, Other]\n"
    "- priority: one of [High, Medium, Low]\n"
    "- urgency_score: integer between 1 and 10\n"
    "- reason: one sentence quoting specific words from the description\n\n"
    "Complaint: {description}\n\n"
    "Rules:\n"
    "- Use ONLY the allowed values listed above\n"
    "- If description contains: accident, injury, collapse, fire, danger,\n"
    "  child, hospital, hazard → priority MUST be High\n"
    "- reason must reference actual words from the description\n"
    "- Return valid JSON only, no extra text"
)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _score_categories(description_lower: str) -> dict[str, int]:
    """Return a keyword hit-count per category for the lowercased description."""
    scores: dict[str, int] = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        scores[category] = sum(1 for kw in keywords if kw in description_lower)
    return scores


def _pick_best_category(scores: dict[str, int]) -> tuple[str, int]:
    """Return (best_category, top_score) from a category→score dict."""
    best = max(scores, key=lambda c: scores[c])
    return best, scores[best]


def _find_matched_keyword(description_lower: str, category: str) -> str:
    """Return the first matching keyword found in description for the given category."""
    for kw in CATEGORY_KEYWORDS.get(category, []):
        if kw in description_lower:
            return kw
    return category.lower()


def _derive_priority(description_lower: str) -> str:
    """Derive priority from severity and tone keywords; never raises."""
    try:
        if any(kw in description_lower for kw in SEVERITY_KEYWORDS):
            return "High"
        if any(kw in description_lower for kw in _HIGH_TONE_WORDS):
            return "High"
        if any(kw in description_lower for kw in _LOW_TONE_WORDS):
            return "Low"
        return "Medium"
    except Exception:
        return "Medium"


def _urgency_score(priority: str) -> int:
    """Return a random urgency score in the band matching the given priority."""
    try:
        if priority == "High":
            return 8
        if priority == "Low":
            return 2
        return 5
    except Exception:
        return 5


def _algorithm_classify(complaint: dict) -> dict:
    """Run keyword-based classification and return category, priority, urgency_score, reason, confidence."""
    try:
        desc_lower: str = str(complaint.get("description", "")).lower()
        scores = _score_categories(desc_lower)
        best_category, top_score = _pick_best_category(scores)

        priority = _derive_priority(desc_lower)
        score = _urgency_score(priority)
        matched_kw = _find_matched_keyword(desc_lower, best_category)
        reason = (
            f"Description mentions '{matched_kw}', "
            f"indicating a {best_category} issue with {priority} priority."
        )

        return {
            "category": best_category,
            "priority": priority,
            "urgency_score": score,
            "reason": reason,
            "confidence": top_score,  # internal only — stripped before output
        }
    except Exception:
        return {
            "category": "Other",
            "priority": "Medium",
            "urgency_score": 5,
            "reason": "Unable to determine category from description.",
            "confidence": 0,
        }


def call_llm(prompt: str) -> str:
    """Call Groq LLM using the provided prompt and return the response text."""
    api_key: str | None = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY is not set.")
    
    client = groq.Groq(api_key=api_key)
    
    try:
        response = client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            model="llama-3.3-70b-versatile",
            temperature=0,
        )
        if response.choices[0].message.content:
            return response.choices[0].message.content
        return ""
    except Exception as e:
        raise RuntimeError(f"Groq API call failed: {e}")

def _llm_classify(description: str, algo_result: dict) -> dict:
    """Call LLM via Groq for ambiguous cases; returns algo_result on any failure."""
    try:
        prompt = _PROMPT_TEMPLATE.replace("{description}", description)
        raw = call_llm(prompt).strip()

        # Strip markdown fences if the LLM wraps output in ```json ... ```
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        data: dict = json.loads(raw)

        # Validate required fields — fall back to algo if anything is wrong
        category: str = str(data.get("category", "")).strip()
        priority: str = str(data.get("priority", "")).strip()

        if category not in ALLOWED_CATEGORIES:
            return algo_result
        if priority not in ("High", "Medium", "Low"):
            return algo_result

        try:
            urgency_score = int(data.get("urgency_score", _urgency_score(priority)))
            urgency_score = max(1, min(10, urgency_score))  # clamp to [1, 10]
        except (ValueError, TypeError):
            urgency_score = _urgency_score(priority)

        reason: str = str(data.get("reason", "")).strip() or algo_result["reason"]

        return {
            "category": category,
            "priority": priority,
            "urgency_score": urgency_score,
            "reason": reason,
            "confidence": 2,  # LLM result treated as high-confidence
        }

    except Exception:
        return algo_result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify(complaints: list[dict]) -> list[dict]:
    """Classify each complaint with category, priority, urgency_score, and reason using hybrid algorithm+LLM."""
    results: list[dict] = []

    for complaint in complaints:
        try:
            # --- Step 1: Algorithm -------------------------------------------
            algo_result = _algorithm_classify(complaint)
            confidence: int = algo_result.get("confidence", 0)

            # --- Step 2: LLM (only for ambiguous cases) ----------------------
            # HIGH confidence = 2+ keyword hits → trust algorithm, skip LLM
            # LOW / NO confidence = 0 or 1 hit  → call LLM
            if confidence >= 2:
                classification = algo_result
            else:
                description: str = str(complaint.get("description", ""))
                classification = _llm_classify(description, algo_result)

            # --- Merge: preserve all Agent 1 keys, add new fields -----------
            enriched = dict(complaint)  # shallow copy — never mutate input
            enriched["category"] = classification["category"]
            enriched["priority"] = classification["priority"]
            enriched["urgency_score"] = classification["urgency_score"]
            enriched["reason"] = classification["reason"]
            
            # --- Step 3: Root Cause -----------------------------------------
            if enriched["priority"] in ("High", "Medium"):
                desc: str = str(complaint.get("description", ""))
                try:
                    rc_prompt = f"You are an urban infrastructure expert. In one sentence, what is the most likely root cause of this complaint: {desc}"
                    enriched["root_cause"] = call_llm(rc_prompt).strip()
                except Exception:
                    enriched["root_cause"] = "Could not determine root cause"
            else:
                enriched["root_cause"] = "Not analyzed"

        except Exception:
            # Last-resort fallback: preserve original complaint, add safe defaults
            enriched = dict(complaint)
            enriched.setdefault("category", "Other")
            enriched.setdefault("priority", "Medium")
            enriched.setdefault("urgency_score", 5)
            enriched.setdefault(
                "reason", "Classification failed; default values applied."
            )
            enriched.setdefault("root_cause", "Not analyzed")

        results.append(enriched)

    return results
