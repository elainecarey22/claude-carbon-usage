#!/usr/bin/env python3
"""
carbon_now.py
-------------
Report the estimated carbon footprint of a Claude Code session against
the live carbon intensity of your electricity grid region.

The grid region defaults to IE (Ireland). Set ELECTRICITY_MAPS_ZONE in
your environment, or pass --zone, to use a different region.

Usage:
  python scripts/carbon_now.py                          # current project, latest session
  python scripts/carbon_now.py --all                    # all sessions for this project
  python scripts/carbon_now.py --session <id>           # specific session
  python scripts/carbon_now.py --project <path>         # different project path
  python scripts/carbon_now.py --zone US-CAL-CISO       # use a specific grid region
  python scripts/carbon_now.py --tokens 1000 500        # manual token input (input output)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv
from claude_energy import summarise_usage, wh_to_gco2
from electricity_maps import DEFAULT_ZONE, get_carbon_intensity_live, zone_label
from session_reader import list_sessions, project_usage, session_usage

load_dotenv()

_BAR_WIDTH = 40

# Grid carbon intensity thresholds (gCO₂/kWh).
# No single standard defines these exact boundaries; they reflect UK/European
# grid monitoring conventions (e.g. National Grid ESO Carbon Intensity API).
# The EU Taxonomy Delegated Act (2021) sets a stricter formal threshold of
# 100 gCO₂e/kWh for electricity generation to qualify as "clean":
# https://ecostandard.org/wp-content/uploads/2021/12/EUTaxonomy_100g_7points.pdf
# National Grid ESO Carbon Intensity API (UK reference bands):
# https://carbonintensity.org.uk
_GRID_THRESHOLDS = {  # gCO₂/kWh
    "clean": 150,
    "moderate": 300,
}


def _grid_label(intensity: float) -> str:
    if intensity < _GRID_THRESHOLDS["clean"]:
        return "clean  ✓"
    if intensity < _GRID_THRESHOLDS["moderate"]:
        return "moderate"
    return "dirty  ✗"


def _bar(value: float, max_value: float, width: int = _BAR_WIDTH) -> str:
    filled = int(round(value / max_value * width)) if max_value > 0 else 0
    return "█" * filled + "░" * (width - filled)


def _fmt_wh(wh: float) -> str:
    if wh < 1:
        return f"{wh * 1000:.1f} mWh"
    return f"{wh:.3f} Wh"


def _fmt_gco2(gco2: float) -> str:
    if gco2 < 1:
        return f"{gco2 * 1000:.1f} mgCO₂"
    return f"{gco2:.2f} gCO₂"


def report(usage: dict, carbon_intensity: float, label: str = "Session", zone: str = DEFAULT_ZONE) -> None:
    s = summarise_usage(usage)
    gco2 = wh_to_gco2(s["estimated_wh"], carbon_intensity)

    total_tokens = (
        s["output_tokens"] + s["input_tokens"]
        + s["cache_write_tokens"] + s["cache_read_tokens"]
    )

    print()
    print(f"  {'─' * 52}")
    print(f"  Claude Code Carbon Report — {label}")
    print(f"  {'─' * 52}")
    print()
    grid_name = f"{zone_label(zone)} grid now:"
    print(f"  {grid_name:<18} {carbon_intensity:>6.0f} gCO₂/kWh  [{_grid_label(carbon_intensity)}]")
    print()
    print(f"  Token breakdown ({total_tokens:,} total):")
    print(f"    Output          {s['output_tokens']:>10,}  (generation)")
    print(f"    Fresh input     {s['input_tokens']:>10,}  (context processing)")
    print(f"    Cache write     {s['cache_write_tokens']:>10,}  (KV cache creation)")
    print(f"    Cache read      {s['cache_read_tokens']:>10,}  (KV cache hits)")
    print()
    print(f"  Estimated energy:  {_fmt_wh(s['estimated_wh'])}")
    print(f"  Estimated carbon:  {_fmt_gco2(gco2)}")
    print()

    # Visual bar showing carbon footprint
    # Reference: boiling a kettle ≈ 30,000 gCO₂ at 300 gCO₂/kWh (100 Wh)
    # We'll scale bar to 1 gCO₂ for a session-level view
    ref = max(gco2, 1.0)
    print(f"  {_bar(gco2, ref * 2)} {_fmt_gco2(gco2)}")
    print(f"  {'─' * 52}")
    print()
    print("  Note: energy is a rough estimate (±an order of magnitude); the grid")
    print("  intensity is measured. Best for relative comparison, not absolute")
    print("  numbers — see 'How accurate is this?' in the README.")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Code carbon footprint vs your electricity grid")
    parser.add_argument("--project", default=".", help="project path (default: current directory)")
    parser.add_argument("--session", default=None, help="specific session ID")
    parser.add_argument("--all", action="store_true", help="aggregate all sessions for the project")
    parser.add_argument(
        "--tokens", nargs=2, metavar=("INPUT", "OUTPUT"), type=int,
        help="manual token counts: --tokens <input> <output>",
    )
    parser.add_argument(
        "--zone", default=DEFAULT_ZONE,
        help=f"Electricity Maps zone code (default: {DEFAULT_ZONE}, "
             "or set ELECTRICITY_MAPS_ZONE)",
    )
    args = parser.parse_args()

    # Fetch live carbon intensity
    print(f"\n  Fetching live carbon intensity for zone {args.zone}...")
    try:
        data = get_carbon_intensity_live(zone=args.zone)
        carbon_intensity = data["carbonIntensity"]
        updated_at = data.get("updatedAt", "unknown")
        print(f"  Grid data updated: {updated_at}")
    except Exception as e:
        print(f"  Error fetching carbon intensity: {e}", file=sys.stderr)
        sys.exit(1)

    # Get token usage
    if args.tokens:
        usage = {
            "input_tokens": args.tokens[0],
            "output_tokens": args.tokens[1],
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        label = f"manual ({args.tokens[0]:,} in / {args.tokens[1]:,} out)"
    elif args.all:
        usage = project_usage(args.project)
        label = "All sessions"
    elif args.session:
        sessions = list_sessions(args.project)
        matched = [s for s in sessions if s.stem == args.session]
        if not matched:
            print(f"  Session {args.session!r} not found in {args.project}", file=sys.stderr)
            sys.exit(1)
        usage = session_usage(matched[0])
        label = f"Session {args.session[:8]}…"
    else:
        # Default: most recent session
        sessions = list_sessions(args.project)
        if not sessions:
            print(f"  No sessions found for project: {args.project}", file=sys.stderr)
            sys.exit(1)
        latest = sessions[-1]
        usage = session_usage(latest)
        label = f"Latest session ({latest.stem[:8]}…)"

    report(usage, carbon_intensity, label=label, zone=args.zone)


if __name__ == "__main__":
    main()
