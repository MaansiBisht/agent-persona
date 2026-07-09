from __future__ import annotations

import dataclasses
from datetime import datetime

from agent_persona.models import Profile

# Recency decay: a signal not seen in `period` days loses `base` of its weight.
_DECAY_BASE = 0.9
_DECAY_PERIOD_DAYS = 30.0
_CONF_FLOOR = 0.3        # below this (after decay) a signal is dropped from injection

# Final injection caps — keep the injected context focused.
_MAX_PREFS = 8
_MAX_PATTERNS = 5
_MAX_CORRECTIONS = 5


def _days_between(then_iso: str, now_iso: str) -> float:
    try:
        then = datetime.fromisoformat(then_iso)
        now = datetime.fromisoformat(now_iso)
    except (ValueError, TypeError):
        return 0.0
    return max(0.0, (now - then).total_seconds() / 86400.0)


def _decay(confidence: float, last_seen: str, now: str) -> float:
    days = _days_between(last_seen, now)
    return confidence * (_DECAY_BASE ** (days / _DECAY_PERIOD_DAYS))


def signal_id(signal: object) -> str:
    """Stable id for a learned signal, used by the mute list."""
    from agent_persona.models import CorrectionSignal, Preference, RequestPattern

    if isinstance(signal, Preference):
        return f"pref:{signal.text}"
    if isinstance(signal, RequestPattern):
        return f"pattern:{signal.trigger}"
    if isinstance(signal, CorrectionSignal):
        return f"correction:{signal.kind}"
    raise TypeError(f"no signal_id for {type(signal)!r}")


_STACK_PREFIX = {"languages": "lang", "frameworks": "framework", "tools": "tool"}


def _filter_stack(counts: dict[str, int], kind: str, muted: set[str]) -> dict[str, int]:
    prefix = _STACK_PREFIX[kind]
    return {k: v for k, v in counts.items() if f"{prefix}:{k}" not in muted}


def apply_rules(profile: Profile, now: str) -> Profile:
    """Return a transient view of the profile for injection: muted-filtered,
    recency-decayed, floor-filtered, ranked, and capped. The stored profile is
    NOT mutated — decay is applied at compile time so it never compounds.

    Manual preferences are exempt from decay and always kept (unless muted).
    """
    muted = set(profile.muted)

    manual = [
        p for p in profile.preferences
        if p.source == "manual" and signal_id(p) not in muted
    ]
    learned: list = []
    for p in profile.preferences:
        if p.source == "manual" or signal_id(p) in muted:
            continue
        decayed = _decay(p.confidence, p.last_seen, now)
        if decayed >= _CONF_FLOOR:
            learned.append(dataclasses.replace(p, confidence=round(decayed, 2)))
    learned.sort(key=lambda p: p.confidence, reverse=True)
    preferences = tuple(manual + learned[:_MAX_PREFS])

    patterns = []
    for rp in profile.request_patterns:
        if signal_id(rp) in muted:
            continue
        decayed = _decay(rp.confidence, rp.last_seen, now)
        if decayed >= _CONF_FLOOR:
            patterns.append(dataclasses.replace(rp, confidence=round(decayed, 2)))
    patterns.sort(key=lambda r: r.confidence, reverse=True)

    corrections = []
    for c in profile.corrections:
        if signal_id(c) in muted:
            continue
        decayed = _decay(c.confidence, c.last_seen, now)
        if decayed >= _CONF_FLOOR:
            corrections.append(dataclasses.replace(c, confidence=round(decayed, 2)))
    corrections.sort(key=lambda c: c.confidence, reverse=True)

    return dataclasses.replace(
        profile,
        languages=_filter_stack(profile.languages, "languages", muted),
        frameworks=_filter_stack(profile.frameworks, "frameworks", muted),
        tools=_filter_stack(profile.tools, "tools", muted),
        preferences=preferences,
        request_patterns=tuple(patterns[:_MAX_PATTERNS]),
        corrections=tuple(corrections[:_MAX_CORRECTIONS]),
    )
