from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from filelock import FileLock

from agent_persona.models import (
    CodingStyle,
    CorrectionSignal,
    Preference,
    Profile,
    RequestPattern,
)


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def default_store() -> Path:
    return _home() / ".agent-persona"


def load_profile(store: Path | None = None) -> Profile:
    path = (store or default_store()) / "profile.json"
    if not path.exists():
        from datetime import datetime, timezone
        return Profile.empty(datetime.now(timezone.utc).isoformat())
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _from_dict(data)
    except (json.JSONDecodeError, KeyError, OSError):
        bak = path.with_suffix(".json.bak")
        if bak.exists():
            try:
                return _from_dict(json.loads(bak.read_text(encoding="utf-8")))
            except Exception:
                pass
        from datetime import datetime, timezone
        return Profile.empty(datetime.now(timezone.utc).isoformat())


def save_profile(profile: Profile, store: Path | None = None) -> None:
    store = store or default_store()
    store.mkdir(parents=True, exist_ok=True)
    path = store / "profile.json"

    lock_path = store / ".profile.lock"
    with FileLock(lock_path):
        if path.exists():
            shutil.copy2(path, path.with_suffix(".json.bak"))
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_to_dict(profile), indent=2), encoding="utf-8")
        tmp.replace(path)


def merge_profile(base: Profile, other: Profile, now: str) -> Profile:
    """Return a new Profile merging other into base. Neither input is mutated."""
    # Decay old stack counts before adding this session so abandoned tech fades.
    languages = _merge_counts(_decay_counts(base.languages), other.languages)
    frameworks = _merge_counts(_decay_counts(base.frameworks), other.frameworks)
    tools = _merge_counts(_decay_counts(base.tools), other.tools)

    pref_map: dict[str, Preference] = {p.text.lower(): p for p in base.preferences}
    for p in other.preferences:
        key = p.text.lower()
        existing = pref_map.get(key)
        if existing is None:
            pref_map[key] = p
        elif existing.source == "manual":
            pass  # manual prefs are never overwritten
        elif p.source == "manual":
            pref_map[key] = p
        elif p.confidence > existing.confidence:
            # higher-quality source wins outright
            pref_map[key] = p
        else:
            # same or lower confidence — repeated observation boosts it
            boosted = min(0.95, existing.confidence + 0.05)
            pref_map[key] = Preference(
                text=existing.text,
                confidence=boosted,
                source=existing.source,
                last_seen=p.last_seen,
            )

    prefs = tuple(
        sorted(pref_map.values(), key=lambda p: p.confidence, reverse=True)[:50]
    )
    style = other.coding_style if other.coding_style.indent != "unknown" else base.coding_style

    return Profile(
        version=1,
        languages=_cap(languages, 20),
        frameworks=_cap(frameworks, 15),
        tools=_cap(tools, 15),
        preferences=prefs,
        coding_style=style,
        last_updated=now,
        sessions_processed=base.sessions_processed + other.sessions_processed,
        machine_fingerprint=base.machine_fingerprint,
        request_patterns=base.request_patterns,
        corrections=base.corrections,
        muted=tuple(dict.fromkeys(base.muted + other.muted)),
    )


def _merge_counts(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    result = dict(a)
    for k, v in b.items():
        result[k] = result.get(k, 0) + v
    return result


# Per-session decay knob (~34-session half-life); truncation self-prunes to 0.
_STACK_DECAY = 0.98


def _decay_counts(d: dict[str, int]) -> dict[str, int]:
    decayed = {k: int(v * _STACK_DECAY) for k, v in d.items()}
    return {k: v for k, v in decayed.items() if v > 0}


def _cap(d: dict[str, int], n: int) -> dict[str, int]:
    if len(d) <= n:
        return d
    return dict(sorted(d.items(), key=lambda x: x[1], reverse=True)[:n])


def _to_dict(p: Profile) -> dict:
    return {
        "version": p.version,
        "stack": {
            "languages": p.languages,
            "frameworks": p.frameworks,
            "tools": p.tools,
        },
        "preferences": [
            {
                "text": pref.text,
                "confidence": pref.confidence,
                "source": pref.source,
                "last_seen": pref.last_seen,
            }
            for pref in p.preferences
        ],
        "coding_style": {
            "indent": p.coding_style.indent,
            "indent_size": p.coding_style.indent_size,
            "test_frequency": p.coding_style.test_frequency,
        },
        "last_updated": p.last_updated,
        "sessions_processed": p.sessions_processed,
        "machine_fingerprint": p.machine_fingerprint,
        "request_patterns": [
            {
                "trigger": rp.trigger,
                "always_include": list(rp.always_include),
                "confidence": rp.confidence,
                "seen_count": rp.seen_count,
                "last_seen": rp.last_seen,
            }
            for rp in p.request_patterns
        ],
        "corrections": [
            {
                "kind": c.kind,
                "count": c.count,
                "confidence": c.confidence,
                "last_seen": c.last_seen,
            }
            for c in p.corrections
        ],
        "muted": list(p.muted),
    }


def _from_dict(d: dict) -> Profile:
    stack = d.get("stack", {})
    prefs = tuple(
        Preference(
            text=p["text"],
            confidence=float(p["confidence"]),
            source=p.get("source", "rule"),
            last_seen=p.get("last_seen", d.get("last_updated", "")),
        )
        for p in d.get("preferences", [])
    )
    request_patterns = tuple(
        RequestPattern(
            trigger=rp["trigger"],
            always_include=tuple(rp.get("always_include", [])),
            confidence=float(rp.get("confidence", 0.0)),
            seen_count=int(rp.get("seen_count", 0)),
            last_seen=rp.get("last_seen", d.get("last_updated", "")),
        )
        for rp in d.get("request_patterns", [])
    )
    corrections = tuple(
        CorrectionSignal(
            kind=c["kind"],
            count=int(c.get("count", 0)),
            confidence=float(c.get("confidence", 0.0)),
            last_seen=c.get("last_seen", d.get("last_updated", "")),
        )
        for c in d.get("corrections", [])
    )
    cs = d.get("coding_style", {})
    return Profile(
        version=d.get("version", 1),
        languages=stack.get("languages", {}),
        frameworks=stack.get("frameworks", {}),
        tools=stack.get("tools", {}),
        preferences=prefs,
        coding_style=CodingStyle(
            indent=cs.get("indent", "unknown"),
            indent_size=int(cs.get("indent_size", 4)),
            test_frequency=cs.get("test_frequency", "unknown"),
        ),
        last_updated=d.get("last_updated", ""),
        sessions_processed=int(d.get("sessions_processed", 0)),
        machine_fingerprint=d.get("machine_fingerprint", ""),
        request_patterns=request_patterns,
        corrections=corrections,
        muted=tuple(d.get("muted", [])),
    )
