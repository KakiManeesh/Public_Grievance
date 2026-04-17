"""
ingestion.py — Agent 1 in the civic complaint pipeline.

Reads raw complaints.csv, validates every row, derives location via reverse geocoding,
and returns a clean list of complaint dicts for Agent 2 (Classifier).
"""

import pandas as pd

from utils import parse_timestamp, validate_coords, reverse_geocode


def ingest(filepath: str) -> list[dict]:
    """Read complaints CSV, validate and enrich every row, and return 70 clean complaint dicts."""

    df = pd.read_csv(filepath)

    results: list[dict] = []

    for _, row in df.iterrows():
        # ------------------------------------------------------------------ #
        # 1. Cast primitive fields — safe fallbacks on any conversion failure #
        # ------------------------------------------------------------------ #
        try:
            complaint_id = int(row["id"])
        except (ValueError, TypeError):
            complaint_id = 0

        try:
            lat = float(row["lat"])
        except (ValueError, TypeError):
            lat = 0.0

        try:
            lng = float(row["lng"])
        except (ValueError, TypeError):
            lng = 0.0

        # ------------------------------------------------------------------ #
        # 2. Parse timestamp — falls back to datetime.now() inside helper    #
        # ------------------------------------------------------------------ #
        try:
            timestamp = parse_timestamp(str(row["timestamp"]))
        except Exception:
            from datetime import datetime
            timestamp = datetime.now()

        # ------------------------------------------------------------------ #
        # 3. Derive location from coordinates                                #
        #    validate_coords() → False for None / NaN / out-of-Hyderabad     #
        #    reverse_geocode() → "Unknown Area" on any API failure           #
        # ------------------------------------------------------------------ #
        try:
            if validate_coords(lat, lng):
                location = reverse_geocode(lat, lng)
            else:
                location = "Unknown Area"
        except Exception:
            location = "Unknown Area"

        if location == "Unknown Area":
            location_flagged = True
            flag_reason = "Location could not be determined"
        else:
            location_flagged = False
            flag_reason = ""

        # ------------------------------------------------------------------ #
        # 4. Normalise string fields                                         #
        # ------------------------------------------------------------------ #
        try:
            description = str(row["description"]).strip()
        except Exception:
            description = ""

        try:
            source = str(row["source"]).strip()
        except Exception:
            source = ""

        try:
            # Note: CSV column header is "City" (capital C)
            city = str(row["City"]).strip()
        except Exception:
            city = ""

        # ------------------------------------------------------------------ #
        # 5. Assemble complaint dict with exactly the required keys          #
        # ------------------------------------------------------------------ #
        complaint: dict = {
            "id":               complaint_id,
            "description":      description,
            "lat":              lat,
            "lng":              lng,
            "source":           source,
            "timestamp":        timestamp,
            "city":             city,
            "location":         location,
            "location_flagged": location_flagged,
            "flag_reason":      flag_reason,
            "status":           "Open",   # All new complaints start as Open
        }

        results.append(complaint)

    # ---------------------------------------------------------------------- #
    # 6. Guard: every row in → every row out.  Never silently drop a row.    #
    # ---------------------------------------------------------------------- #
    if len(results) != len(df):
        raise ValueError(
            f"Silent row drop detected: CSV has {len(df)} rows "
            f"but only {len(results)} complaint dicts produced."
        )

    return results
