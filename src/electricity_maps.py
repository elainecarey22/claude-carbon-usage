"""
electricity_maps.py
-------------------
Fetch carbon intensity data from the Electricity Maps API.

Docs: https://static.electricitymaps.com/api/docs/index.html

Set ELECTRICITY_MAPS_API_KEY in your environment (or .env file).
Ireland grid zone: IE
"""

from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.electricitymap.org/v3"
DEFAULT_ZONE = "IE"


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
