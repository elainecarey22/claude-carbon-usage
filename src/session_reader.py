"""
session_reader.py
-----------------
Read Claude Code session transcripts and extract token usage.

Claude Code saves transcripts as JSONL files under:
  ~/.claude/projects/<sanitised-path>/<session-id>.jsonl

Each assistant turn has a `message.usage` dict with token counts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


_CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"


def _projects_dir_for(project_path: str | Path) -> Path:
    """Return the ~/.claude/projects/<hash> directory for a given project path."""
    sanitised = re.sub(r"[^a-zA-Z0-9]", "-", str(Path(project_path).resolve()))
    return _CLAUDE_PROJECTS / sanitised


def list_sessions(project_path: str | Path) -> list[Path]:
    """Return sorted list of JSONL transcript paths for a project."""
    d = _projects_dir_for(project_path)
    if not d.exists():
        return []
    return sorted(d.glob("*.jsonl"))


def read_session_usage(transcript: Path) -> list[dict]:
    """
    Parse a JSONL transcript and return a list of usage dicts,
    one per assistant API call.
    """
    usages = []
    with transcript.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "assistant":
                usage = obj.get("message", {}).get("usage")
                if usage:
                    usages.append(usage)
    return usages


def aggregate_usage(usages: list[dict]) -> dict:
    """Sum token counts across a list of usage dicts."""
    totals: dict[str, int] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    for u in usages:
        for key in totals:
            totals[key] += u.get(key, 0)
    return totals


def session_usage(transcript: Path) -> dict:
    """Aggregate token usage for a single session transcript."""
    return aggregate_usage(read_session_usage(transcript))


def project_usage(project_path: str | Path, session_id: str | None = None) -> dict:
    """
    Aggregate token usage across all sessions for a project,
    or for a specific session if session_id is given.
    """
    sessions = list_sessions(project_path)
    if session_id:
        sessions = [s for s in sessions if s.stem == session_id]
    all_usages = []
    for s in sessions:
        all_usages.extend(read_session_usage(s))
    return aggregate_usage(all_usages)
