"""
geocoder.py — Coordinate validation and reverse geocoding for the civic complaint pipeline.

Used by Agent 1 (Ingestion) and Agent 3 (Cluster).
External dependency: requests. All other imports are stdlib.
Includes file-based cache to avoid repeated Nominatim API calls.
"""

import json
import math
import os
import time
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Hyderabad bounding box (Greater Hyderabad Municipal Corporation area)
# ---------------------------------------------------------------------------

_HYDERABAD_BOUNDS: dict = {
    "lat_min": 17.20,
    "lat_max": 17.65,
    "lng_min": 78.20,
    "lng_max": 78.65,
}

# Nominatim reverse geocoding endpoint
_NOMINATIM_URL: str = "https://nominatim.openstreetmap.org/reverse"

# Locality fields extracted from Nominatim response, in priority order
_LOCALITY_FIELDS: tuple = ("suburb", "neighbourhood", "city_district", "county")

# Cache file path — sits in data/ folder
_CACHE_FILE: str = os.path.join(
    os.path.dirname(__file__), "..", "data", "geocode_cache.json"
)


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _load_cache() -> dict:
    """Load geocode cache from disk, return empty dict if not found."""
    try:
        if os.path.exists(_CACHE_FILE):
            with open(_CACHE_FILE, "r") as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError):
        pass
    return {}


def _save_cache(cache: dict) -> None:
    """Persist geocode cache to disk."""
    try:
        with open(_CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except IOError:
        pass


def _clean_locality(raw: str) -> str:
    """Strip ward prefix from Nominatim suburb names e.g. 'Ward 104 Kondapur' → 'Kondapur'."""
    if raw.lower().startswith("ward"):
        parts = raw.split()
        cleaned = " ".join(parts[2:])
        return cleaned if cleaned else raw
    return raw


# ---------------------------------------------------------------------------
# 1. validate_coords
# ---------------------------------------------------------------------------


def validate_coords(lat: float, lng: float) -> bool:
    """Return True only if lat/lng fall within Greater Hyderabad bounds; False otherwise."""
    try:
        if lat is None or lng is None:
            return False

        lat = float(lat)
        lng = float(lng)

        if math.isnan(lat) or math.isnan(lng):
            return False
        if math.isinf(lat) or math.isinf(lng):
            return False

        # Reject (0.0, 0.0) — classic missing-data sentinel
        if lat == 0.0 and lng == 0.0:
            return False

        return (
            _HYDERABAD_BOUNDS["lat_min"] <= lat <= _HYDERABAD_BOUNDS["lat_max"]
            and _HYDERABAD_BOUNDS["lng_min"] <= lng <= _HYDERABAD_BOUNDS["lng_max"]
        )
    except (TypeError, ValueError, Exception):
        return False


# ---------------------------------------------------------------------------
# 2. reverse_geocode
# ---------------------------------------------------------------------------


def reverse_geocode(lat: float, lng: float) -> str:
    """Convert lat/lng to a human-readable locality name via Nominatim with disk cache."""
    # Build cache key — rounded to 4 decimal places (~11m precision)
    key = f"{round(lat, 4)},{round(lng, 4)}"

    # Load cache and check for hit
    cache = _load_cache()
    if key in cache:
        return cache[key]  # ← instant, no API call

    # Cache miss — hit Nominatim API
    try:
        response = requests.get(
            _NOMINATIM_URL,
            params={
                "lat": lat,
                "lon": lng,
                "format": "json",
                "zoom": 14,
            },
            headers={"User-Agent": "CivixPulse/1.0"},
            timeout=5,
        )

        # Always sleep after every API call to respect Nominatim rate limits
        time.sleep(1)

        response.raise_for_status()
        data: dict = response.json()
        address: dict = data.get("address", {})

        # Walk the priority list and return the first non-empty value
        result = "Unknown Area"
        for field in _LOCALITY_FIELDS:
            locality: Optional[str] = address.get(field)
            if locality:
                result = _clean_locality(str(locality).strip())
                break

    except requests.exceptions.Timeout:
        time.sleep(1)
        result = "Unknown Area"
    except requests.exceptions.RequestException:
        time.sleep(1)
        result = "Unknown Area"
    except (ValueError, KeyError, AttributeError, Exception):
        result = "Unknown Area"

    # Save to cache before returning
    cache[key] = result
    _save_cache(cache)

    return result
