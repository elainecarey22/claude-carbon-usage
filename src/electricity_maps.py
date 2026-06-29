"""
electricity_maps.py
-------------------
Fetch carbon intensity data from the Electricity Maps API.

Docs: https://static.electricitymaps.com/api/docs/index.html

Set ELECTRICITY_MAPS_API_KEY in your environment (or .env file).
Set ELECTRICITY_MAPS_ZONE to choose your grid region (default: IE, Ireland).
Zone codes: https://api.electricitymap.org/v3/zones
"""

from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.electricitymap.org/v3"

# The grid region to price energy against. Override with the
# ELECTRICITY_MAPS_ZONE environment variable (or the --zone CLI flag).
DEFAULT_ZONE = os.environ.get("ELECTRICITY_MAPS_ZONE", "IE").strip() or "IE"

# Friendly display names for common zones. Falls back to the raw zone
# code for anything not listed (see zone_label).
ZONE_LABELS = {
    "IE": "Ireland",
    "FR": "France",
    "NO": "Norway",
    "DK": "Denmark",
    "ES": "Spain",
    "DE": "Germany",
    "GB": "Great Britain",
    "US-NE-ISNE": "New England",
    "US-NY-NYIS": "New York",
    "US-MIDA-PJM": "Mid-Atlantic (PJM)",
    "US-CAL-CISO": "California",
}


def zone_label(zone: str) -> str:
    """Human-friendly name for a zone code, falling back to the code itself."""
    return ZONE_LABELS.get(zone, zone)


def _headers() -> dict:
    key = os.environ.get("ELECTRICITY_MAPS_API_KEY")
    if not key:
        raise EnvironmentError("ELECTRICITY_MAPS_API_KEY not set")
    return {"auth-token": key}


def get_carbon_intensity_live(zone: str = DEFAULT_ZONE) -> dict:
    """Fetch the current carbon intensity for a zone (gCO₂eq/kWh)."""
    resp = requests.get(
        f"{BASE_URL}/carbon-intensity/latest",
        params={"zone": zone},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()
