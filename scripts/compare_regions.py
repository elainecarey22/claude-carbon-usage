#!/usr/bin/env python3
"""
compare_regions.py
------------------
Compare the estimated carbon footprint of a Claude Code session across
multiple electricity grid regions.

Usage:
  python scripts/compare_regions.py                     # current project, latest session
  python scripts/compare_regions.py --all               # all sessions for this project
  python scripts/compare_regions.py --session <id>      # specific session
  python scripts/compare_regions.py --zones IE US-NY-NYIS US-NE-ISNE  # custom zone list
  python scripts/compare_regions.py --tokens 1000 500   # manual token input
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv
from claude_energy import summarise_usage, wh_to_gco2
from electricity_maps import get_carbon_intensity_live
from session_reader import list_sessions, project_usage, session_usage

load_dotenv()

DEFAULT_ZONES: list[tuple[str, str]] = [
    ("FR",          "France"),
    ("NO",          "Norway"),
    ("DK",          "Denmark"),
    ("ES",          "Spain"),
    ("IE",          "Ireland"),
    ("DE",          "Germany"),
    ("US-NE-ISNE",  "New England"),
    ("US-NY-NYIS",  "New York"),
    ("US-MIDA-PJM", "Mid-Atlantic (PJM)"),
]


def fetch_intensities(zones: list[tuple[str, str]]) -> list[tuple[str, str, float | None]]:
    results = []
    for zone, label in zones:
        try:
            data = get_carbon_intensity_live(zone=zone)
            results.append((zone, label, float(data["carbonIntensity"])))
        except Exception as e:
            print(f"  Warning: could not fetch {zone}: {e}", file=sys.stderr)
            results.append((zone, label, None))
    return results


def _bar(value: float, max_value: float, width: int = 30) -> str:
    filled = int(round(value / max_value * width)) if max_value > 0 else 0
    return "█" * filled + "░" * (width - filled)


def _fmt_gco2(gco2: float) -> str:
    if gco2 < 1:
        return f"{gco2 * 1000:.1f} mgCO₂"
    return f"{gco2:.2f} gCO₂"


# Grid carbon intensity thresholds (gCO₂/kWh).
# No single standard defines these exact boundaries; they reflect UK/European
# grid monitoring conventions (e.g. National Grid ESO Carbon Intensity API).
# The EU Taxonomy Delegated Act (2021) sets a stricter formal threshold of
# 100 gCO₂e/kWh for electricity generation to qualify as "clean":
# https://ecostandard.org/wp-content/uploads/2021/12/EUTaxonomy_100g_7points.pdf
# National Grid ESO Carbon Intensity API (UK reference bands):
# https://carbonintensity.org.uk
_CLEAN_THRESHOLD = 150
_MODERATE_THRESHOLD = 300


def _grid_label(intensity: float) -> str:
    if intensity < _CLEAN_THRESHOLD:
        return "clean   "
    if intensity < _MODERATE_THRESHOLD:
        return "moderate"
    return "dirty   "


def report(usage: dict, zone_data: list[tuple[str, str, float | None]], session_label: str) -> None:
    s = summarise_usage(usage)
    total_tokens = (
        s["output_tokens"] + s["input_tokens"]
        + s["cache_write_tokens"] + s["cache_read_tokens"]
    )

    valid = [(z, l, ci) for z, l, ci in zone_data if ci is not None]
    if not valid:
        print("  No zone data available.", file=sys.stderr)
        return

    max_ci = max(ci for _, _, ci in valid)
    max_gco2 = wh_to_gco2(s["estimated_wh"], max_ci)

    label_width = max(len(l) for _, l, _ in valid)

    print()
    print(f"  {'─' * 62}")
    print(f"  Regional Carbon Comparison — {session_label}")
    print(f"  {'─' * 62}")
    print()
    print(f"  Session: {total_tokens:,} tokens  |  ~{s['estimated_wh']:.1f} Wh estimated")
    print()
    print(f"  {'Region':<{label_width}}   {'gCO₂/kWh':>9}   {'Est. CO₂':>10}   {'Grid':<8}   Chart")
    print(f"  {'─' * label_width}   {'─' * 9}   {'─' * 10}   {'─' * 8}   {'─' * 30}")

    results = []
    for zone, label, ci in valid:
        gco2 = wh_to_gco2(s["estimated_wh"], ci)
        results.append((zone, label, ci, gco2))

    # Sort by carbon intensity ascending (cleanest first)
    results.sort(key=lambda r: r[2])

    for zone, label, ci, gco2 in results:
        bar = _bar(gco2, max_gco2)
        print(f"  {label:<{label_width}}   {ci:>8.0f}   {_fmt_gco2(gco2):>10}   {_grid_label(ci)}   {bar}")

    print()
    cleanest = results[0]
    dirtiest = results[-1]
    if cleanest[3] > 0:
        ratio = dirtiest[3] / cleanest[3]
        print(f"  {dirtiest[1]} emits {ratio:.1f}x more CO₂ than {cleanest[1]} for this session.")
    print()
    print(f"  {'─' * 62}")
    print()
    print("  Note: energy figures are estimates (±order of magnitude).")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare Claude Code session carbon footprint across grid regions"
    )
    parser.add_argument("--project", default=".", help="project path (default: current directory)")
    parser.add_argument("--session", default=None, help="specific session ID")
    parser.add_argument("--all", action="store_true", help="aggregate all sessions for the project")
    parser.add_argument(
        "--tokens", nargs=2, metavar=("INPUT", "OUTPUT"), type=int,
        help="manual token counts: --tokens <input> <output>",
    )
    parser.add_argument(
        "--zones", nargs="+", metavar="ZONE",
        help="space-separated list of Electricity Maps zone codes to compare",
    )
    args = parser.parse_args()

    zones = DEFAULT_ZONES
    if args.zones:
        zones = [(z, z) for z in args.zones]

    # Get token usage
    if args.tokens:
        usage = {
            "input_tokens": args.tokens[0],
            "output_tokens": args.tokens[1],
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        session_label = f"manual ({args.tokens[0]:,} in / {args.tokens[1]:,} out)"
    elif args.all:
        usage = project_usage(args.project)
        session_label = "All sessions"
    elif args.session:
        sessions = list_sessions(args.project)
        matched = [s for s in sessions if s.stem == args.session]
        if not matched:
            print(f"  Session {args.session!r} not found in {args.project}", file=sys.stderr)
            sys.exit(1)
        usage = session_usage(matched[0])
        session_label = f"Session {args.session[:8]}…"
    else:
        sessions = list_sessions(args.project)
        if not sessions:
            print(f"  No sessions found for project: {args.project}", file=sys.stderr)
            sys.exit(1)
        latest = sessions[-1]
        usage = session_usage(latest)
        session_label = f"Latest session ({latest.stem[:8]}…)"

    print(f"\n  Fetching live carbon intensity for {len(zones)} zone(s)...")
    zone_data = fetch_intensities(zones)

    report(usage, zone_data, session_label)


if __name__ == "__main__":
    main()
