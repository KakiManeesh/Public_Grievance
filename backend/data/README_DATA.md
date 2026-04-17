# 📊 Data Directory

This folder contains the raw input data and configuration files
used by the backend pipeline. The data is intentionally kept minimal —
agents are responsible for deriving intelligence from it, not reading
pre-filled answers.

---

## 📁 Files

| File | Purpose |
|---|---|
| `complaints.csv` | 70 raw civic complaints — pipeline input |
| `historical_data.csv` | Same complaints with full derived fields — reference/analytics only |
| `departments.json` | Department routing config with SLA timings |

---

## 🗂️ complaints.csv — Pipeline Input

### Overview
- **70 rows** of raw civic complaints from Hyderabad
- **Intentionally stripped** — no category, priority, urgency, location, or status
- Agents derive all intelligence from `description`, `lat`, `lng`, and `timestamp`
- **City:** Hyderabad, Telangana, India

### Columns (7 total)

| Column | Type | Description | Example |
|---|---|---|---|
| `id` | int | Unique complaint identifier | 1 |
| `description` | string | Raw complaint text — the only semantic signal | "Massive pothole near metro station..." |
| `lat` | float | Latitude coordinate | 17.435587 |
| `lng` | float | Longitude coordinate | 78.344401 |
| `source` | string | Submission channel | WhatsApp / Portal / Twitter / Email / Mobile App |
| `timestamp` | datetime | When complaint was submitted | 16-04-26 14:22 |
| `City` | string | City name | Hyderabad |

### What is NOT in this file (derived by agents)

| Field | Derived By | How |
|---|---|---|
| `category` | Agent 2 — Classifier | LLM + keyword rules on `description` |
| `priority` | Agent 2 — Classifier | LLM + severity keyword detection |
| `urgency_score` | Agent 2 — Classifier | Scored 1–10 based on description severity |
| `location` | Agent 1 — Ingestion | `reverse_geocode(lat, lng)` via Nominatim API |
| `status` | Agent 1 — Ingestion | Hardcoded `"Open"` for all new complaints |
| `cluster_id` | Agent 3 — Cluster | DBSCAN on lat/lng within same category |
| `sla_deadline` | Agent 4 — Resolver | `timestamp + sla_hours[priority]` |

### Sample Row
```csv
id,description,lat,lng,source,timestamp,City
1,Massive pothole near metro station causing bike accidents,17.435587,78.344401,WhatsApp,16-04-26 14:22,Hyderabad
```

---

## 🗂️ historical_data.csv — Reference Only

### Overview
This is the same 70 complaints but with **all derived fields pre-filled**.
It is **not used by the pipeline** — it serves as:
- Ground truth to validate agent output accuracy
- Historical dataset for analytics and dashboard trend charts
- Fallback reference if agents produce unexpected results

### Additional Columns (vs complaints.csv)

| Column | Type | Description |
|---|---|---|
| `category` | string | Pre-labelled category |
| `priority` | string | Pre-labelled priority |
| `urgency_score` | int | Pre-labelled score (1–10) |
| `location` | string | Pre-labelled locality name |
| `status` | string | Mix of Open / In Progress / Resolved |

> ⚠️ Never feed `historical_data.csv` into the live pipeline.
> It is read-only reference data.

---

## 🏢 departments.json

### Overview
Maps each complaint category to its responsible government department,
SLA resolution timings, and contact email.

### Structure
```json
{
  "CategoryName": {
    "department": "Full department name",
    "sla_hours": {
      "High": <int>,
      "Medium": <int>,
      "Low": <int>
    },
    "contact": "email@dept.gov.in"
  }
}
```

### SLA Hours Reference

| Category | High | Medium | Low |
|---|---|---|---|
| Roads | 6 hrs | 24 hrs | 72 hrs |
| Sanitation | 4 hrs | 12 hrs | 48 hrs |
| Water | 3 hrs | 12 hrs | 48 hrs |
| Electricity | 2 hrs | 8 hrs | 24 hrs |
| Traffic | 1 hr | 6 hrs | 24 hrs |
| Safety | 1 hr | 4 hrs | 24 hrs |
| Public Property | 6 hrs | 24 hrs | 72 hrs |

---

## 🔧 How to Use in Code

### Load raw complaints (pipeline input)
```python
import pandas as pd
df = pd.read_csv("data/complaints.csv")
# Columns: id, description, lat, lng, source, timestamp, City
```

### Load historical data (analytics only)
```python
df_hist = pd.read_csv("data/historical_data.csv")
# Full columns including category, priority, urgency_score, location, status
```

### Load departments config
```python
import json
with open("data/departments.json") as f:
    departments = json.load(f)

# Get SLA for a resolved complaint
sla = departments["Water"]["sla_hours"]["High"]   # returns 3
dept = departments["Water"]["department"]          # returns "HMWSSB..."
```

---

## 📌 Agent Consumption Map

| Agent | File Used | Columns Consumed |
|---|---|---|
| Agent 1 — Ingestion | `complaints.csv` | All 7 columns |
| Agent 2 — Classifier | Output of Agent 1 | `description` only |
| Agent 3 — Cluster | Output of Agent 2 | `lat`, `lng`, `category` |
| Agent 4 — Resolver | Output of Agent 3 + `departments.json` | `category`, `priority`, `timestamp` |

---

## ⚠️ Important Notes

- `timestamp` format is `DD-MM-YY HH:MM` — parsed by `utils/helpers.py`
- `lat`/`lng` are validated against Hyderabad bounds by `utils/geocoder.py`
- `City` column is title-cased — note the capital `C` in the header
- All coordinates are real Hyderabad lat/lng values — compatible with Folium maps
- `source` column simulates multi-channel ingestion (Twitter/WhatsApp/Portal/Email/App)
