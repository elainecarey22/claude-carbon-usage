#!/usr/bin/env python3
"""
carbon_track.py
---------------
Machine-wide carbon tracker for Claude Code sessions.

Designed to run from a global SessionEnd hook (~/.claude/settings.json), this
records the carbon cost of *every* Claude Code session — across all projects —
into a single SQLite database at ~/.claude/carbon/usage.db.

It reuses this repo's energy model (src/claude_energy.py) and grid lookup
(src/electricity_maps.py), so machine-wide numbers stay consistent with the
per-project ledger that scripts/project_total.py maintains.

As a SessionEnd hook the payload arrives as JSON on stdin:
  { "session_id": "...", "transcript_path": "...", "cwd": "..." }

Usage:
  # Hook mode (reads the SessionEnd JSON payload from stdin)
  python scripts/carbon_track.py

  # Manual: record one transcript
  python scripts/carbon_track.py --transcript ~/.claude/projects/<dir>/<id>.jsonl

  # Print the machine-wide report
  python scripts/carbon_track.py --report

  # Use a different database location
  python scripts/carbon_track.py --report --db /tmp/usage.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from dotenv import load_dotenv

# Load the repo's .env explicitly (by absolute path): when this runs as a
# global hook the working directory is some *other* project, so the default
# CWD-relative .env lookup would miss the API key and zone configuration.
load_dotenv(_REPO_ROOT / ".env")

from claude_energy import summarise_usage, wh_to_gco2  # noqa: E402
from electricity_maps import DEFAULT_ZONE, get_carbon_intensity_live, zone_label  # noqa: E402
from session_reader import session_usage  # noqa: E402

_DEFAULT_DB = Path.home() / ".claude" / "carbon" / "usage.db"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, timeout=10)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id        TEXT PRIMARY KEY,
            project           TEXT,
            cwd               TEXT,
            zone              TEXT,
            carbon_intensity  REAL,
            output_tokens     INTEGER,
            input_tokens      INTEGER,
            cache_write_tokens INTEGER,
            cache_read_tokens INTEGER,
            total_tokens      INTEGER,
            estimated_wh      REAL,
            estimated_gco2    REAL,
            first_seen        TEXT,
            updated_at        TEXT
        )
        """
    )
    return con


def record_session(
    con: sqlite3.Connection,
    *,
    session_id: str,
    transcript: Path,
    project: str,
    cwd: str,
    zone: str,
) -> dict:
    """Price one transcript and upsert it into the database."""
    s = summarise_usage(session_usage(transcript))
    total = (
        s["output_tokens"] + s["input_tokens"]
        + s["cache_write_tokens"] + s["cache_read_tokens"]
    )

    # Fetch live grid intensity. If it fails (e.g. expired free-tier key), still
    # record the energy figures — carbon is left NULL and can be backfilled.
    intensity: float | None = None
    gco2: float | None = None
    try:
        data = get_carbon_intensity_live(zone=zone)
        intensity = float(data["carbonIntensity"])
        gco2 = round(wh_to_gco2(s["estimated_wh"], intensity), 4)
    except Exception as e:  # noqa: BLE001 — hook must never crash the session
        print(f"  carbon intensity unavailable ({e}); recorded energy only",
              file=sys.stderr)

    con.execute(
        """
        INSERT INTO sessions (
            session_id, project, cwd, zone, carbon_intensity,
            output_tokens, input_tokens, cache_write_tokens, cache_read_tokens,
            total_tokens, estimated_wh, estimated_gco2, first_seen, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            project=excluded.project,
            cwd=excluded.cwd,
            zone=excluded.zone,
            carbon_intensity=excluded.carbon_intensity,
            output_tokens=excluded.output_tokens,
            input_tokens=excluded.input_tokens,
            cache_write_tokens=excluded.cache_write_tokens,
            cache_read_tokens=excluded.cache_read_tokens,
            total_tokens=excluded.total_tokens,
            estimated_wh=excluded.estimated_wh,
            estimated_gco2=excluded.estimated_gco2,
            updated_at=excluded.updated_at
        """,
        (
            session_id, project, cwd, zone, intensity,
            s["output_tokens"], s["input_tokens"], s["cache_write_tokens"],
            s["cache_read_tokens"], total, round(s["estimated_wh"], 4), gco2,
            _now(), _now(),
        ),
    )
    con.commit()
    return {
        "session_id": session_id,
        "project": project,
        "zone": zone,
        "total_tokens": total,
        "estimated_wh": round(s["estimated_wh"], 4),
        "estimated_gco2": gco2,
        "carbon_intensity": intensity,
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


def report(con: sqlite3.Connection) -> None:
    rows = con.execute(
        "SELECT project, COUNT(*), SUM(total_tokens), SUM(estimated_wh), "
        "SUM(COALESCE(estimated_gco2, 0)) "
        "FROM sessions GROUP BY project ORDER BY SUM(estimated_wh) DESC"
    ).fetchall()

    if not rows:
        print("\n  No sessions recorded yet.\n")
        return

    n_sessions, total_tokens, total_wh, total_gco2 = con.execute(
        "SELECT COUNT(*), SUM(total_tokens), SUM(estimated_wh), "
        "SUM(COALESCE(estimated_gco2, 0)) FROM sessions"
    ).fetchone()

    print()
    print(f"  {'─' * 62}")
    print(f"  Machine-wide Claude Code Carbon — all projects")
    print(f"  {'─' * 62}")
    print()
    print(f"  Sessions tracked:  {n_sessions}")
    print(f"  Total tokens:      {total_tokens:,}")
    print(f"  Total energy:      {_fmt_wh(total_wh)}")
    print(f"  Total carbon:      {_fmt_gco2(total_gco2)}")
    print()
    print(f"  By project:")
    name_width = max(len(r[0] or "unknown") for r in rows)
    name_width = min(max(name_width, 7), 32)
    for project, count, tokens, wh, gco2 in rows:
        label = (project or "unknown")[:name_width]
        print(
            f"    {label:<{name_width}}  "
            f"{count:>3} sess  "
            f"{tokens:>12,} tok  "
            f"{_fmt_gco2(gco2):>12}"
        )
    print()
    print(f"  {'─' * 62}")
    print(f"  TOTAL  {_fmt_gco2(total_gco2):>46}")
    print(f"  {'─' * 62}")
    print(f"  Database: {_DEFAULT_DB}")
    print()


def _payload_from_stdin() -> dict:
    if sys.stdin.isatty():
        return {}
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Machine-wide carbon tracker for Claude Code sessions"
    )
    parser.add_argument("--report", action="store_true", help="print the machine-wide report and exit")
    parser.add_argument("--transcript", help="path to a session transcript (.jsonl) to record")
    parser.add_argument("--session", help="session id (defaults to the transcript filename)")
    parser.add_argument("--cwd", help="project working directory for labelling")
    parser.add_argument("--db", default=str(_DEFAULT_DB), help=f"database path (default: {_DEFAULT_DB})")
    args = parser.parse_args()

    db_path = Path(args.db).expanduser()
    con = _connect(db_path)

    if args.report:
        report(con)
        return

    payload = _payload_from_stdin()
    transcript_str = args.transcript or payload.get("transcript_path")
    if not transcript_str:
        print("  No transcript provided (need stdin payload or --transcript)", file=sys.stderr)
        sys.exit(1)

    transcript = Path(transcript_str).expanduser()
    if not transcript.exists():
        print(f"  Transcript not found: {transcript}", file=sys.stderr)
        sys.exit(1)

    cwd = args.cwd or payload.get("cwd") or ""
    project = Path(cwd).name if cwd else "unknown"
    session_id = args.session or payload.get("session_id") or transcript.stem

    result = record_session(
        con,
        session_id=session_id,
        transcript=transcript,
        project=project,
        cwd=cwd,
        zone=DEFAULT_ZONE,
    )

    carbon = (
        _fmt_gco2(result["estimated_gco2"]) if result["estimated_gco2"] is not None
        else "carbon n/a"
    )
    print(
        f"  Recorded {session_id[:8]}… [{project}] "
        f"{result['total_tokens']:,} tokens → {carbon} "
        f"({zone_label(result['zone'])})"
    )


if __name__ == "__main__":
    main()
