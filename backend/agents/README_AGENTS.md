# 🧠 Agents Directory

This folder contains the four core AI agents powering the
Agentic Public Grievance Intelligence System.
Each agent is a focused, single-responsibility module that
processes civic complaints end-to-end.

---

## 📁 Folder Structure

```bash
backend/agents/
├── __init__.py      # Agent registry & exports
├── ingestion.py     # Agent 1 — Data Ingestion & Normalization
├── classifier.py    # Agent 2 — Complaint Classification
├── cluster.py       # Agent 3 — Geo-Spatial Clustering
└── resolver.py      # Agent 4 — SLA Routing & Resolution
```

---

## 🔄 Pipeline Overview

```
complaints.csv (7 columns — raw, no labels)
     │
     ▼
[Agent 1: Ingestion]
  → Validates coords, derives location via reverse_geocode()
  → Sets status = "Open" for all complaints
  → Output: 70 clean complaint dicts
     │
     ▼
[Agent 2: Classifier]
  → Algorithm: keyword rules catch obvious cases instantly
  → LLM: handles ambiguous cases only (saves tokens)
  → Derives: category + priority + urgency_score + reason
     │
     ▼
[Agent 3: Cluster]
  → DBSCAN on lat/lng, grouped per category
  → Output: complaints with cluster_id assigned
     │
     ▼
[Agent 4: Resolver]
  → Maps category → department via departments.json
  → Calculates SLA deadline + breach status
  → Output: final resolution tickets
```

---

# ⚙️ Agent 1 — `ingestion.py`

## What it Does
Reads raw `complaints.csv` (7 columns, no labels), validates every
row, derives missing fields, and emits clean complaint objects
for Agent 2 to consume.

## How it Works
- Reads CSV using `pandas`
- Parses `timestamp` using `parse_timestamp()` from utils
- Validates `lat`/`lng` using `validate_coords()` from utils
- Derives `location` from coordinates using `reverse_geocode(lat, lng)`
- Sets `status = "Open"` for every complaint (all incoming = new)
- Normalizes `source` and `city` → strip + title case
- Casts `id` → int, `lat`/`lng` → float
- Asserts `len(output) == 70` — never silently drops rows

## Key Logic
```python
def ingest(filepath: str) -> list[dict]:
    df = pd.read_csv(filepath)
    results = []
    for _, row in df.iterrows():
        complaint = {
            "id":          int(row["id"]),
            "description": str(row["description"]).strip(),
            "lat":         float(row["lat"]),
            "lng":         float(row["lng"]),
            "source":      str(row["source"]).strip().title(),
            "timestamp":   parse_timestamp(row["timestamp"]),
            "city":        str(row["City"]).strip(),
            "location":    reverse_geocode(float(row["lat"]), float(row["lng"])),
            "status":      "Open"
        }
        results.append(complaint)
    assert len(results) == len(df), "Silent row drop detected!"
    return results
```

## ✅ Success Criteria
- All 70 rows in → 70 clean dicts out
- Every complaint has `status = "Open"`
- Every complaint has a `location` string (never None)
- All timestamps are valid `datetime` objects
- All lat/lng pass Hyderabad bounds check

## ⚠️ Failure Modes
Nominatim rate-limit errors · Timestamp format mismatch ·
Float casting errors on malformed coords · Silent row drops

---

# 🤖 Agent 2 — `classifier.py`

## What it Does
Derives `category`, `priority`, `urgency_score`, and `reason`
from the complaint `description` text using a hybrid
Algorithm + LLM approach.

## How it Works — Hybrid Pipeline

### Step 1: Algorithm (runs first, always free)
Rule-based keyword matching handles the obvious cases instantly:
- Checks description against category keyword lists
- Detects severity keywords → forces `priority = "High"`
- If confidence is high (clear keyword match) → skip LLM entirely
- If ambiguous → pass to LLM

### Step 2: LLM (runs only for ambiguous cases)
- Sends `description` to LLM via Groq API
- Uses a strict prompt
- Uses Pydantic output parser to enforce allowed values
- Falls back to algorithm result if LLM output is invalid

### Step 3: Root Cause (for High/Medium priority)
- Sends `description` to LLM via Groq API for one-sentence root cause analysis

## Keyword Maps
```python
CATEGORY_KEYWORDS = {
    "Roads":         ["pothole", "road", "gravel", "pavement", "asphalt", "divider"],
    "Sanitation":    ["garbage", "waste", "trash", "drain", "sewage", "dump"],
    "Water":         ["water", "pipe", "leak", "supply", "sewage", "overflow"],
    "Electricity":   ["light", "power", "electric", "wire", "transformer", "outage"],
    "Traffic":       ["signal", "traffic", "accident", "congestion", "zebra", "speed"],
    "Safety":        ["crime", "theft", "assault", "unsafe", "danger", "police"],
    "Public Property": ["park", "bench", "wall", "building", "monument", "footpath"]
}

SEVERITY_KEYWORDS = [
    "accident", "injury", "collapse", "hazard",
    "school", "hospital", "fire", "danger", "child"
]
```

## Urgency Score Logic
```python
High   → urgency_score = 8
Medium → urgency_score = 5
Low    → urgency_score = 2
(SLA Breach: +2, Sensitive Location: +1, Capped at 10)
```

## LLM Prompt
```python
prompt = ChatPromptTemplate.from_template("""
You are a civic complaint classifier for Hyderabad municipal services.
Given the complaint description, output ONLY these four fields:
- category: one of [Roads, Sanitation, Water, Electricity, Traffic, Safety, Public Property]
- priority: one of [High, Medium, Low]
- urgency_score: integer 1-10
- reason: one sentence citing specific words from the description

Description: {description}

Rules:
- Use ONLY allowed values — no variations or abbreviations
- Severity keywords (injury/fire/child/hospital/collapse) = always High
- reason must quote words from the description, never paraphrase
""")
```

## Allowed Values

| Field | Allowed Values |
|---|---|
| `category` | Roads · Sanitation · Water · Electricity · Traffic · Safety · Public Property · Health · Parks · Noise · Other |
| `priority` | High · Medium · Low |
| `urgency_score` | Integer 1–10 |
| `root_cause` | String (one sentence) or "Not analyzed" |

## ✅ Success Criteria
- Every complaint has a valid category from the allowed 7
- Severity keyword complaints always get `priority = "High"`
- `urgency_score` is always an integer between 1 and 10
- LLM is called only when algorithm is not confident
- No complaint exits this agent without all 4 fields

## ⚠️ Failure Modes
Taxonomy drift · LLM hallucinating categories · Missed severity
keywords · Pydantic parser failing on malformed LLM output

---

# 📍 Agent 3 — `cluster.py`

## What it Does
Groups spatially close complaints of the same category together
to detect hotspots and avoid duplicate department assignments
for the same underlying issue.

## How it Works
- Runs DBSCAN separately for each of the 7 categories
- Uses Haversine distance metric on radians-converted coordinates
- `eps = 0.5/6371` (0.5 km radius), `min_samples = 2`
- Assigns `cluster_id` per complaint (`-1` = isolated, no cluster)
- Generates cluster summary with centroid, count, dominant priority

## Algorithm
```python
from sklearn.cluster import DBSCAN
import numpy as np

def cluster(complaints: list[dict]) -> list[dict]:
    df = pd.DataFrame(complaints)
    df["cluster_id"] = -1

    for category in df["category"].unique():
        mask = df["category"] == category
        coords = np.radians(df.loc[mask, ["lat", "lng"]].values)
        db = DBSCAN(eps=0.5/6371, min_samples=2, metric="haversine")
        df.loc[mask, "cluster_id"] = db.fit_predict(coords)

    return df.to_dict(orient="records")
```

## Cluster Summary Output
```json
{
  "cluster_id": 3,
  "category": "Roads",
  "complaint_ids": ,
  "centroid": { "lat": 17.4398, "lng": 78.3756 },
  "count": 3,
  "dominant_priority": "High"
}
```

## ✅ Success Criteria
- Complaints within 500m of same category are grouped
- No cross-category clustering ever occurs
- Isolated complaints always get `cluster_id = -1`
- Centroid coordinates are valid Hyderabad lat/lng values
- Total complaint count is preserved (70 in → 70 out)

## ⚠️ Failure Modes
Wrong `eps` scale (degrees vs radians) · Cross-category merging ·
Overwriting existing `cluster_id` across category loops

---

# 🏛️ Agent 4 — `resolver.py`

## What it Does
Assigns each complaint to the correct government department,
calculates the SLA deadline, checks for breaches, and generates
a structured resolution ticket.

## How it Works
- Loads `departments.json` for department name, SLA hours, and contact
- Maps `category` → department
- Calculates `sla_deadline = timestamp + timedelta(hours=sla_hours[priority])`
- Calls `is_sla_breached()` and `get_time_remaining()` from utils
- Calls `format_resolution_ticket()` from utils to build final output

## Key Logic
```python
def resolve(complaints: list[dict], departments: dict) -> list[dict]:
    tickets = []
    for complaint in complaints:
        cat      = complaint["category"]
        priority = complaint["priority"]
        dept     = departments[cat]
        deadline = calculate_sla_deadline(
                     complaint["timestamp"], priority, cat, departments
                   )
        ticket = format_resolution_ticket(complaint, dept, deadline)
        tickets.append(ticket)
    return tickets
```

## Output Ticket Schema

| Field | Type | Description |
|---|---|---|
| `complaint_id` | int | Links back to original complaint |
| `description` | string | Original complaint text |
| `category` | string | Selected category |
| `location` | string | Reverse-geocoded locality |
| `location_flagged` | bool | True if location unknown |
| `flag_reason` | string | Reason for location flag |
| `priority` | string | High / Medium / Low |
| `urgency_score` | int | 1–10 score |
| `root_cause` | string | One sentence root cause |
| `status` | string | Always "Open" at this stage |
| `department` | string | Assigned government department |
| `contact` | string | Department contact email |
| `reported_at` | ISO datetime | Original complaint timestamp |
| `sla_deadline` | ISO datetime | When it must be resolved by |
| `sla_breached` | bool | True if current time > deadline |
| `time_remaining` | string | "2h 30m remaining" or "OVERDUE by Xh Ym" |
| `is_overdue` | bool | Whether it is overdue |
| `overdue_minutes` | int | Minutes overdue, null if not |
| `remaining_minutes` | int | Minutes remaining, null if overdue |

## ✅ Success Criteria
- Every complaint has an assigned department
- SLA deadline is correctly calculated for all 3 priorities × 7 categories
- `sla_breached` is always a boolean, never null
- `time_remaining` is always a human-readable string
- 70 complaints in → 70 tickets out

## ⚠️ Failure Modes
Category not found in `departments.json` · Timezone-naive
datetime comparison · Null timestamps from Agent 1

---

# 🔌 `__init__.py` — Agent Registry

Exports all four agents for clean imports in `app.py`:

```python
from agents import ingest, classify, cluster, resolve

tickets = resolve(
    cluster(
        classify(
            ingest("data/complaints.csv")
        )
    ),
    departments
)
```

---

# 🔗 Inter-Agent Data Flow

```
ingestion.py  → produces: List[dict] with id, description, lat, lng,
                           source, timestamp, city, location, status

classifier.py → consumes: above
              → adds:     category, priority, urgency_score, reason

cluster.py    → consumes: above
              → adds:     cluster_id

resolver.py   → consumes: above + departments.json
              → produces: List[ResolutionTicket] (final output)
```

---

# ⚠️ Global Failure Modes

| Failure | Agent | Prevention |
|---|---|---|
| Silent row drops | Ingestion | Assert `len(output) == 70` |
| Nominatim rate limit | Ingestion | `time.sleep(1)` in geocoder |
| LLM hallucinated category | Classifier | Pydantic enum parser + algo fallback |
| Algorithm misses ambiguous case | Classifier | LLM as second pass |
| Wrong distance scale | Cluster | Always use radians, not degrees |
| Cross-category clustering | Cluster | Loop DBSCAN per category |
| Category missing in departments | Resolver | Validate JSON keys at startup |
| Timezone-naive datetime math | Resolver | Use timezone-naive consistently |
