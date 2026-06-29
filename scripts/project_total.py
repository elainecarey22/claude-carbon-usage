#!/usr/bin/env python3
"""
project_total.py
----------------
Calculate the cumulative carbon cost of developing this project across all
Claude Code sessions. Maintains a ledger so each session is only processed
once — subsequent runs only price in new sessions.

Ledger is stored at: data/carbon_ledger.json

Usage:
  python scripts/project_total.py             # update ledger and print total
  python scripts/project_total.py --reprocess # recalculate all sessions from scratch
  python scripts/project_total.py --project <path>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv
from claude_energy import summarise_usage, wh_to_gco2
from electricity_maps import get_carbon_intensity_live
from session_reader import list_sessions, session_usage

load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LEDGER_PATH = _PROJECT_ROOT / "data" / "carbon_ledger.json"


def load_ledger() -> dict:
    if _LEDGER_PATH.exists():
        with _LEDGER_PATH.open() as f:
            return json.load(f)
    return {"zone": "IE", "sessions": {}}


def save_ledger(ledger: dict) -> None:
    _LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LEDGER_PATH.open("w") as f:
        json.dump(ledger, f, indent=2)


def process_session(transcript: Path, carbon_intensity: float) -> dict:
    """Calculate and return a ledger entry for one session."""
    usage = session_usage(transcript)
    s = summarise_usage(usage)
    gco2 = wh_to_gco2(s["estimated_wh"], carbon_intensity)
    return {
        "estimated_wh": round(s["estimated_wh"], 4),
        "estimated_gco2": round(gco2, 4),
        "carbon_intensity_used": carbon_intensity,
        "output_tokens": s["output_tokens"],
        "input_tokens": s["input_tokens"],
        "cache_write_tokens": s["cache_write_tokens"],
        "cache_read_tokens": s["cache_read_tokens"],
        "total_tokens": (
            s["output_tokens"] + s["input_tokens"]
            + s["cache_write_tokens"] + s["cache_read_tokens"]
        ),
        "processed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _fmt_gco2(gco2: float) -> str:
    if gco2 < 1:
        return f"{gco2 * 1000:.1f} mgCO₂"
    if gco2 >= 1000:
        return f"{gco2 / 1000:.3f} kgCO₂"
    return f"{gco2:.2f} gCO₂"


def _fmt_wh(wh: float) -> str:
    if wh >= 1000:
        return f"{wh / 1000:.3f} kWh"
    return f"{wh:.2f} Wh"


def print_report(ledger: dict, newly_added: list[str]) -> None:
    sessions = ledger["sessions"]
    if not sessions:
        print("\n  No sessions in ledger yet.\n")
        return

    total_gco2 = sum(s["estimated_gco2"] for s in sessions.values())
    total_wh = sum(s["estimated_wh"] for s in sessions.values())
    total_tokens = sum(s["total_tokens"] for s in sessions.values())

    print()
    print(f"  {'─' * 58}")
    print(f"  Project Carbon Ledger — {_LEDGER_PATH.name}")
    print(f"  {'─' * 58}")
    print()
    print(f"  Sessions tracked:  {len(sessions)}")
    print(f"  Total tokens:      {total_tokens:,}")
    print(f"  Total energy:      {_fmt_wh(total_wh)}")
    print(f"  Total carbon:      {_fmt_gco2(total_gco2)}")
    print()

    if newly_added:
        print(f"  New this run ({len(newly_added)} session{'s' if len(newly_added) != 1 else ''}):")
        for sid in newly_added:
            e = sessions[sid]
            print(
                f"    {sid[:8]}…  "
                f"{e['total_tokens']:>10,} tokens  "
                f"{_fmt_gco2(e['estimated_gco2']):>12}  "
                f"@ {e['carbon_intensity_used']:.0f} gCO₂/kWh"
            )
        print()
    else:
        print("  No new sessions since last run.")
        print()

    print(f"  Per-session breakdown:")
    for sid, e in sorted(sessions.items(), key=lambda x: x[1]["processed_at"]):
        marker = " ← new" if sid in newly_added else ""
        print(
            f"    {sid[:8]}…  "
            f"{e['total_tokens']:>10,} tokens  "
            f"{_fmt_gco2(e['estimated_gco2']):>12}{marker}"
        )

    print()
    print(f"  {'─' * 58}")
    print(f"  TOTAL  {_fmt_gco2(total_gco2):>42}")
    print(f"  {'─' * 58}")
    print()
    print(f"  Ledger saved to: {_LEDGER_PATH}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cumulative carbon cost of this project's Claude Code sessions"
    )
    parser.add_argument("--project", default=".", help="project path (default: current directory)")
    parser.add_argument(
        "--reprocess", action="store_true",
        help="clear the ledger and recalculate all sessions from scratch",
    )
    args = parser.parse_args()

    ledger = {} if args.reprocess else load_ledger()
    if not ledger:
        ledger = {"zone": "IE", "sessions": {}}

    all_sessions = list_sessions(args.project)
    if not all_sessions:
        print(f"\n  No sessions found for project: {args.project}\n", file=sys.stderr)
        sys.exit(1)

    known = set(ledger["sessions"].keys())
    new_sessions = [s for s in all_sessions if s.stem not in known]

    newly_added: list[str] = []

    if new_sessions:
        print(f"\n  {len(new_sessions)} new session(s) to process. Fetching live IE carbon intensity...")
        try:
            data = get_carbon_intensity_live(zone=ledger.get("zone", "IE"))
            carbon_intensity = float(data["carbonIntensity"])
            print(f"  Grid intensity: {carbon_intensity:.0f} gCO₂/kWh (used for new sessions)")
        except Exception as e:
            print(f"  Error fetching carbon intensity: {e}", file=sys.stderr)
            sys.exit(1)

        for transcript in new_sessions:
            sid = transcript.stem
            print(f"  Processing {sid[:8]}…")
            entry = process_session(transcript, carbon_intensity)
            ledger["sessions"][sid] = entry
            newly_added.append(sid)

        save_ledger(ledger)
    else:
        print("\n  Ledger is up to date — no new sessions to process.")

    print_report(ledger, newly_added)


if __name__ == "__main__":
    main()
