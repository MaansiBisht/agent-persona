from __future__ import annotations

import json
from pathlib import Path

from agent_persona.models import CorrectionSignal

_MIN_SESSIONS = 3      # a correction kind must recur across ≥3 distinct sessions
_MIN_PROJECTS = 2      # across ≥2 projects — a habit, not one project's quirk
_MAX_SIGNALS = 5       # the taxonomy is small; cap anyway
_CONF_CAP = 0.85       # behavioral inference, below manual (1.0)


def extract_corrections(store: Path, now: str) -> tuple[CorrectionSignal, ...]:
    """Promote correction kinds seen across enough distinct sessions/projects
    into CorrectionSignals. Confidence re-derived from evidence each run."""
    log_path = store / "corrections.jsonl"
    if not log_path.exists():
        return ()

    kind_sessions: dict[str, set[str]] = {}
    kind_projects: dict[str, set[str]] = {}
    kind_last: dict[str, str] = {}

    with log_path.open(encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            try:
                record = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(record, dict):
                continue
            session_id = record.get("session_id", "")
            project = record.get("project", "")
            ts = record.get("ts", "")
            corrections = record.get("corrections", [])
            if not isinstance(corrections, list):
                continue
            for entry in corrections:
                if isinstance(entry, list) and entry:
                    kind = entry[0]
                elif isinstance(entry, str):
                    kind = entry
                else:
                    continue
                kind_sessions.setdefault(kind, set()).add(session_id)
                if project:
                    kind_projects.setdefault(kind, set()).add(project)
                if ts > kind_last.get(kind, ""):
                    kind_last[kind] = ts

    signals: list[CorrectionSignal] = []
    for kind, sessions in kind_sessions.items():
        n_sessions = len(sessions)
        n_projects = len(kind_projects.get(kind, set()))
        if n_sessions < _MIN_SESSIONS or n_projects < _MIN_PROJECTS:
            continue
        volume = min(1.0, n_sessions / 5)
        confidence = round(min(_CONF_CAP, 0.5 + 0.5 * volume), 2)
        signals.append(CorrectionSignal(
            kind=kind,
            count=n_sessions,
            confidence=confidence,
            last_seen=kind_last.get(kind, now),
        ))

    signals.sort(key=lambda s: s.confidence, reverse=True)
    return tuple(signals[:_MAX_SIGNALS])
