# 🧰 Utils Directory

This folder contains shared utility modules used across all four agents.
These are **not agents themselves** — they are helper functions that ensure consistency and avoid code duplication across the pipeline.

---

## 📁 Folder Structure

```bash id="m2x8pl"
backend/utils/
├── __init__.py     # Exports all utils for clean imports
├── geocoder.py     # Reverse geocoding & coordinate validation
└── helpers.py      # Shared formatting, time, and data utilities
```

---

# 🔌 `__init__.py` — Utils Registry

Exports all utility functions for clean single-line imports:

```python id="j7n4k2"
from utils import reverse_geocode, validate_coords, format_resolution_ticket, get_time_remaining
```

* No logic lives here — it only aggregates exports

---

# 📍 `geocoder.py`

## What it does

Provides coordinate validation and reverse geocoding.

Used by:

* Agent 1 (Ingestion)
* Agent 3 (Cluster)
* Dashboard map views

---

## Why it exists

Ensures:

* Coordinates are valid
* Locations are human-readable
* Lat/Lng matches actual locality (ground truth)

---

## Functions

### `reverse_geocode(lat, lng) -> str`

Converts coordinates → locality name.

### How it works

* Calls OpenStreetMap (Nominatim API)
* Extracts:

  * `suburb` → preferred
  * `neighbourhood`
  * `city_district`
* Falls back to `"Unknown Area"`
* Adds 1-second delay (rate limiting)

```python id="r4y9tx"
import requests
import time

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"

def reverse_geocode(lat: float, lng: float) -> str:
    try:
        response = requests.get(
            NOMINATIM_URL,
            params={"lat": lat, "lon": lng, "format": "json", "zoom": 14},
            headers={"User-Agent": "CivixPulse/1.0"},
            timeout=5
        )
        data = response.json()
        address = data.get("address", {})
        time.sleep(1)

        return (
            address.get("suburb") or
            address.get("neighbourhood") or
            address.get("city_district") or
            "Unknown Area"
        )
    except Exception:
        return "Unknown Area"
```

---

### `validate_coords(lat, lng) -> bool`

Validates whether coordinates lie within Hyderabad bounds.

```python id="d7p3sw"
HYDERABAD_BOUNDS = {
    "lat_min": 17.20, "lat_max": 17.65,
    "lng_min": 78.20, "lng_max": 78.65
}

def validate_coords(lat: float, lng: float) -> bool:
    try:
        return (
            HYDERABAD_BOUNDS["lat_min"] <= lat <= HYDERABAD_BOUNDS["lat_max"] and
            HYDERABAD_BOUNDS["lng_min"] <= lng <= HYDERABAD_BOUNDS["lng_max"]
        )
    except (TypeError, ValueError):
        return False
```

---

## Dependencies

```text id="xk2n91"
requests
```

---

## ✅ Success Criteria

* Returns valid locality for all coordinates
* Never crashes on bad input
* Respects API rate limits
* All coordinates pass Hyderabad bounds check

---

## ⚠️ Failure Modes

* API timeout
* Rate limit (429 errors)
* Invalid coordinates passing validation
* Missing keys in API response

---

# 🧠 `helpers.py`

## What it does

Shared utility functions used across all agents for:

* Time handling
* SLA calculations
* Formatting
* Normalization

---

## Why it exists

Avoids duplication of common logic across agents.

---

## Functions

### `parse_timestamp(ts) -> datetime`

```python id="q1v8dp"
from datetime import datetime

def parse_timestamp(ts: str) -> datetime:
    try:
        return datetime.strptime(ts, "%d-%m-%y %H:%M")
    except (ValueError, TypeError):
        return datetime.now()
```

---

### `calculate_sla_deadline(...)`

```python id="d08zps"
from datetime import timedelta

def calculate_sla_deadline(timestamp, priority, category, departments):
    try:
        hours = departments[category]["sla_hours"][priority]
    except KeyError:
        hours = 72
    return timestamp + timedelta(hours=hours)
```

---

### `is_sla_breached(deadline)`

```python id="p2e9vy"
from datetime import datetime

def is_sla_breached(deadline: datetime) -> bool:
    return datetime.now() > deadline
```

---

### `get_time_remaining(deadline)`

```python id="u4jz3o"
def get_time_remaining(deadline: datetime) -> str:
    delta = deadline - datetime.now()
    total_minutes = int(delta.total_seconds() / 60)

    if total_minutes >= 0:
        h, m = divmod(total_minutes, 60)
        return f"{h}h {m}m remaining"
    else:
        total_minutes = abs(total_minutes)
        h, m = divmod(total_minutes, 60)
        return f"OVERDUE by {h}h {m}m"
```

---

### `normalize_priority(raw)`

```python id="x9e1rf"
PRIORITY_MAP = {
    "urgent": "High", "critical": "High", "high": "High",
    "medium": "Medium", "normal": "Medium", "moderate": "Medium",
    "low": "Low", "minor": "Low"
}

def normalize_priority(raw: str) -> str:
    return PRIORITY_MAP.get(str(raw).strip().lower(), "Medium")
```

---

### `get_urgency_band(score)`

```python id="u8z6xk"
def get_urgency_band(score: int) -> str:
    if score >= 7:
        return "High"
    elif score >= 4:
        return "Medium"
    else:
        return "Low"
```

---

### `format_resolution_ticket(...)`

```python id="p7w2dc"
def format_resolution_ticket(complaint, dept, deadline):
    return {
        "complaint_id": complaint["id"],
        "description": complaint["description"],
        "category": complaint["category"],
        "location": complaint["location"],
        "priority": complaint["priority"],
        "urgency_score": complaint["urgency_score"],
        "status": complaint["status"],
        "department": dept["department"],
        "contact": dept["contact"],
        "reported_at": complaint["timestamp"].isoformat(),
        "sla_deadline": deadline.isoformat(),
        "sla_breached": is_sla_breached(deadline),
        "time_remaining": get_time_remaining(deadline),
        "is_overdue": is_overdue,
        "overdue_minutes": overdue_minutes,
        "remaining_minutes": remaining_minutes,
        "root_cause": complaint.get("root_cause"),
        "location_flagged": complaint.get("location_flagged"),
        "flag_reason": complaint.get("flag_reason")
    }
```

---

## Dependencies

```text id="d2y4mr"
datetime (standard library)
```

---

## ✅ Success Criteria

* All timestamps parsed correctly
* SLA deadlines accurate across categories
* Priority normalization consistent
* Output tickets complete (no null fields)

---

## ⚠️ Failure Modes

* Timestamp format mismatch
* Timezone inconsistencies
* Missing category/priority keys
* SLA fallback masking config issues

---

# 🔗 Dependency Map

| Agent         | Uses                                                                                  |
| ------------- | ------------------------------------------------------------------------------------- |
| ingestion.py  | parse_timestamp, validate_coords, normalize_priority                                  |
| classifier.py | normalize_priority, get_urgency_band                                                  |
| cluster.py    | validate_coords, reverse_geocode                                                      |
| resolver.py   | calculate_sla_deadline, is_sla_breached, format_resolution_ticket, get_time_remaining |

---

# ⚠️ Global Failure Modes

| Failure                     | Module      | Prevention                 |
| --------------------------- | ----------- | -------------------------- |
| Nominatim rate limit (429)  | geocoder.py | Add `time.sleep(1)`        |
| Timestamp mismatch          | helpers.py  | Use fixed format           |
| Timezone issues             | helpers.py  | Use consistent timezone    |
| KeyError in dict lookup     | helpers.py  | Use `.get()` with fallback |
| Invalid coordinates passing | geocoder.py | Reject zero/invalid values |

---
