# ⚙️ Backend

This is the intelligence core of the project — a multi-agent AI pipeline
that ingests raw civic complaint data, classifies and clusters it,
then routes each complaint to the correct government department with
a calculated SLA deadline.

The backend is built with Python + Flask and is designed to be run
as a REST API that the frontend consumes.

---

## 🎯 Objective

Transform a raw CSV of 70 unstructured, unlabelled civic complaints into
structured, department-assigned resolution tickets — automatically, with
zero manual classification — by chaining four specialized AI agents in sequence.

**Input →** `data/complaints.csv` (70 raw complaints — 7 columns, no labels)
**Output →** List of resolution tickets with department, SLA deadline,
             cluster grouping, and breach status
             (category, priority, location, department — all derived by agents)

---

## 📁 Folder Structure
backend/
├── app.py ← Flask API server — entry point
├── README.md ← This file
│
├── agents/ ← The four AI processing agents (pipeline)
│ ├── _init_.py
│ ├── ingestion.py ← Agent 1: Read + validate + derive location + set status
│ ├── classifier.py ← Agent 2: Algorithm + LLM hybrid classification
│ ├── cluster.py ← Agent 3: DBSCAN geo-spatial hotspot detection
│ └── resolver.py ← Agent 4: Department assignment + SLA calc
│
├── data/ ← Static data files
│ ├── complaints.csv ← 70 raw Hyderabad civic complaints (7 cols, no labels)
│ ├── historical_data.csv ← Same 70 complaints pre-labelled (reference only)
│ ├── departments.json ← SLA config + department contact mapping
│ └── README_DATA.md ← Data schema documentation
│
└── utils/ ← Shared helper functions across all agents
├── _init_.py
├── geocoder.py ← Coordinate validation + reverse geocoding
├── helpers.py ← Timestamp parsing, SLA math, ticket formatting
└── README_UTILS.md ← Utils function documentation

text

> 📖 Each subfolder has its own README — read those for deep dives
> into individual agents and utility functions.

---

## 🔄 Pipeline / Flow

The backend processes complaints in a strict linear pipeline.
Each agent's output is the next agent's input.
┌─────────────────────────────────────────────────────────┐
│ complaints.csv — 7 cols, no labels │
│ id, description, lat, lng, source, timestamp, city │
└────────────────────────┬────────────────────────────────┘
│
▼
┌──────────────────────────────┐
│ AGENT 1 — Ingestion │
│ ingestion.py │
│ - Reads + validates CSV │
│ - Derives location from │
│ lat/lng (Nominatim API) │
│ - Sets status = "Open" │
│ - Parses timestamps │
└──────────────┬───────────────┘
│ List[CleanComplaint]
▼
┌──────────────────────────────┐
│ AGENT 2 — Classifier │
│ classifier.py │
│ - Algorithm: keyword rules │
│ (instant, free) │
│ - LLM: ambiguous cases only │
│ (saves tokens) │
│ - Derives category, │
│ priority, urgency_score, │
│ reason │
└──────────────┬───────────────┘
│ List[ClassifiedComplaint]
▼
┌──────────────────────────────┐
│ AGENT 3 — Cluster │
│ cluster.py │
│ - DBSCAN per category │
│ - Haversine distance │
│ - 0.5km radius │
│ - Assigns cluster_id │
└──────────────┬───────────────┘
│ List[ClusteredComplaint]
▼
┌──────────────────────────────┐
│ AGENT 4 — Resolver │
│ resolver.py │
│ - Maps category → │
│ department │
│ - Calculates SLA deadline │
│ - Flags SLA breaches │
│ - Builds resolution ticket │
└──────────────┬───────────────┘
│ List[ResolutionTicket]
▼
┌─────────────────────────────────────────────────────────┐
│ app.py — Flask REST API │
│ Serves tickets to the frontend │
└─────────────────────────────────────────────────────────┘

text

---

## ▶️ How to Run

### Prerequisites
- Python 3.10+
- A Groq API key (for Agent 2 — Classifier) https://console.groq.com/keys

### Step 1 — Navigate to Backend
```bash
cd AI4IMPACT/backend
```

### Step 2 — Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 3 — Set Up Environment Variables
Create a `.env` file at the **project root** (not inside backend/):
```env
GROQ_API_KEY=your_groq_api_key_here
FLASK_ENV=development
FLASK_PORT=5000
```

### Step 4 — Run the Server
```bash
python app.py
```

### Step 5 — Verify It's Working
http://localhost:5000/health ← Should return { "status": "ok" }
http://localhost:5000/api/complaints ← Should return 70 complaint tickets

text

---

## 🚀 `app.py` — The Entry Point

`app.py` is the Flask server that wires the entire pipeline together
and exposes the output as REST API endpoints for the frontend to consume.

### What it Does
- Initializes the Flask app
- Runs the full 4-agent pipeline on startup (or on demand via endpoint)
- Exposes API endpoints that return processed complaint data as JSON
- Handles CORS so the frontend (served separately) can make requests
- Manages top-level error handling for the entire pipeline

### API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/complaints` | All processed complaints with full resolution tickets |
| `GET` | `/api/clusters` | Cluster summaries with centroid + count |
| `GET` | `/api/stats` | Dashboard KPIs (counts by category, priority, status) |
| `GET` | `/api/breached` | Only complaints where SLA is breached |
| `GET` | `/health` | Health check — confirms API is running |
| `POST`| `/api/refresh` | Clear cache and rerun the pipeline |

### Core Logic in `app.py`

```python
from agents import ingest, classify, cluster, resolve
import json

def run_pipeline():
    raw_complaints = ingest("data/complaints.csv")
    classified     = classify(raw_complaints)
    clustered      = cluster(classified)
    tickets        = resolve(clustered, load_departments())
    return tickets

def load_departments():
    with open("data/departments.json") as f:
        return json.load(f)
```

---

## 🔑 Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | ✅ Yes | LLM key for Agent 2 (Classifier) |
| `FLASK_ENV` | Optional | `development` for debug mode |
| `FLASK_PORT` | Optional | Default is `5000` |

Store these in the `.env` file at the project root.
Never commit `.env` to Git.

```env
GROQ_API_KEY=your_groq_api_key_here
FLASK_ENV=development
FLASK_PORT=5000
```

Load in `app.py` using:
```python
from dotenv import load_dotenv
load_dotenv()
```

---

## ✅ Success Criteria

The backend is working correctly when ALL of the following are true:

**Pipeline Level**
- [ ] All 70 complaints ingested with zero silent row drops
- [ ] All 70 complaints have a `location` string derived from lat/lng
- [ ] All 70 complaints have `status = "Open"`
- [ ] All 70 complaints have a valid `category` from the allowed 7
- [ ] All 70 complaints have `priority` as exactly `High`, `Medium`, or `Low`
- [ ] All 70 complaints have a `cluster_id` (even `-1` for isolated)
- [ ] All 70 complaints have a valid ISO `sla_deadline`
- [ ] `sla_breached` is a boolean for every complaint (never `null`)

**Agent Level**
- [ ] Agent 1: `len(output) == 70` — no rows dropped
- [ ] Agent 2: No category outside the allowed 7 values
- [ ] Agent 3: At least 1 cluster formed (2+ nearby same-category complaints)
- [ ] Agent 4: Every `category` resolves to a department in `departments.json`

**API Level**
- [ ] `/health` returns `200 OK`
- [ ] `/api/complaints` returns 70 items in the JSON array
- [ ] `/api/stats` totals add up to 70 across all categories
- [ ] Frontend can call all endpoints without CORS errors

---

## ⚠️ Common Errors & How to Handle Them

### 1. `KeyError: 'category'` in `resolver.py`
**Cause:** Category casing mismatch between classifier output and `departments.json`
**Fix:** Always normalize to Title Case in Agent 2 before passing to Agent 4:
```python
complaint["category"] = complaint["category"].strip().title()
```

---

### 2. `ValueError: time data does not match format`
**Cause:** Timestamp in CSV doesn't match `"%d-%m-%y %H:%M"`
**Fix:** Already handled in `utils/helpers.py` — falls back to `datetime.now()`

---

### 3. LLM returns category not in allowed list
**Cause:** Agent 2 LLM hallucinating a variation like `"Potholes"` instead of `"Roads"`
**Fix:** Pydantic enum parser rejects it → falls back to algorithm result automatically

---

### 4. DBSCAN clusters everything into one giant cluster
**Cause:** `eps` in degrees instead of radians
**Fix:** Always convert coordinates before DBSCAN:
```python
coords = np.radians(df[["lat", "lng"]].values)
db = DBSCAN(eps=0.5/6371, min_samples=2, metric="haversine")
```

---

### 5. `CORS error` on frontend requests
**Cause:** Flask doesn't allow cross-origin requests by default
**Fix:**
```python
from flask_cors import CORS
CORS(app)
```

---

### 6. `ModuleNotFoundError: No module named 'agents'`
**Cause:** Running `app.py` from wrong directory
**Fix:** Always run from inside `backend/`:
```bash
cd backend
python app.py
```

---

### 7. Nominatim returns `429 Too Many Requests`
**Cause:** Missing `time.sleep(1)` or User-Agent header in `geocoder.py`
**Fix:** Already handled in `utils/geocoder.py` — 1s sleep + User-Agent enforced

---

## 🚨 Places to Be Cautious

| Area | Risk | Caution |
|---|---|---|
| Agent 1 → Agent 2 handoff | Missing fields (location, status) | Assert all keys exist before passing |
| Agent 2 Algorithm | Wrong category from partial keyword match | Order keyword lists by specificity |
| Agent 2 LLM | Hallucinated or malformed JSON | Always use Pydantic parser with fallback |
| Agent 3 DBSCAN `eps` | Wrong scale (degrees vs radians) | Convert to radians first, always |
| `departments.json` keys | Must match category names exactly | 7 keys, Title Case, no typos |
| `datetime` math | Timezone-naive comparison bugs | Use timezone-naive consistently |
| Nominatim API | Rate limits + mandatory User-Agent | 1s sleep + User-Agent always |
| `.env` file | API key exposure | Add `.env` to `.gitignore` immediately |
| Silent row drops | Agent 1 drops malformed rows | Assert `len(output) == 70` after ingestion |

---

## 📦 Dependencies
flask # REST API server
flask-cors # Cross-origin request handling
python-dotenv # Load .env variables
pandas # CSV reading + data manipulation
scikit-learn # DBSCAN clustering (Agent 3)
numpy # Coordinate math for Haversine
langchain # LLM chaining for Agent 2
groq # Groq LLM integration
pydantic # Output parsing + validation
requests # Nominatim API calls in geocoder

text

---

## 📖 Further Reading

| Topic | Where to Look |
|---|---|
| Data schema, CSV columns, departments config | `data/README_DATA.md` |
| Each agent's algorithm + success criteria | `agents/README_AGENTS.md` |
| Utility function signatures + usage | `utils/README_UTILS.md` |
| Environment setup + full project overview | Root `README.md` |