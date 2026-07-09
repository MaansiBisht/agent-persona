from __future__ import annotations

import json
from pathlib import Path

from agent_persona.models import RequestPattern

_MIN_SESSIONS = 3      # trigger and pair must each appear in >= 3 distinct sessions
_MIN_FREQ = 0.60       # pair must co-occur in >= 60% of the trigger's sessions
_MIN_PROJECTS = 2      # >= 2 distinct projects — kills single-repo conventions
_MAX_PATTERNS = 10     # cap so SessionStart context stays focused
_CONF_CAP = 0.90       # inferred patterns are never as trusted as manual instructions


def extract_request_patterns(store: Path, now: str) -> tuple[RequestPattern, ...]:
    """Promote (trigger -> followup) transitions seen across enough distinct
    sessions and projects into RequestPattern rules. Confidence is re-derived
    from frequency on every run — never additively ratcheted."""
    log_path = store / "request_patterns.jsonl"
    if not log_path.exists():
        return ()

    trigger_sessions: dict[str, set[str]] = {}
    pair_sessions: dict[tuple[str, str], set[str]] = {}
    pair_projects: dict[tuple[str, str], set[str]] = {}
    pair_last: dict[tuple[str, str], str] = {}

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
            transitions = record.get("transitions", [])
            if not isinstance(transitions, list):
                continue
            for pair in transitions:
                if not (isinstance(pair, list) and len(pair) == 2):
                    continue
                trigger, followup = pair[0], pair[1]
                key = (trigger, followup)
                trigger_sessions.setdefault(trigger, set()).add(session_id)
                pair_sessions.setdefault(key, set()).add(session_id)
                if project:
                    pair_projects.setdefault(key, set()).add(project)
                if ts > pair_last.get(key, ""):
                    pair_last[key] = ts

    candidates: list[RequestPattern] = []
    for (trigger, followup), sessions in pair_sessions.items():
        n_trigger = len(trigger_sessions.get(trigger, set()))
        n_pair = len(sessions)
        n_projects = len(pair_projects.get((trigger, followup), set()))

        if n_trigger < _MIN_SESSIONS or n_pair < _MIN_SESSIONS:
            continue
        freq = n_pair / n_trigger if n_trigger else 0.0
        if freq < _MIN_FREQ:
            continue
        if n_projects < _MIN_PROJECTS:
            continue

        volume = min(1.0, n_pair / 5)
        confidence = round(min(_CONF_CAP, freq * (0.6 + 0.4 * volume)), 2)
        candidates.append(RequestPattern(
            trigger=trigger,
            always_include=(followup,),
            confidence=confidence,
            seen_count=n_pair,
            last_seen=pair_last.get((trigger, followup), now),
        ))

    candidates.sort(key=lambda p: p.confidence, reverse=True)
    return tuple(candidates[:_MAX_PATTERNS])
