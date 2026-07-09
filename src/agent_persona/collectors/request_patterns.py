from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from filelock import FileLock

_RETENTION_DAYS = 90
_MAX_LINES = 2000

# Closed intent vocabulary. First match wins — cheap and deterministic.
INTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("bug_fix",    re.compile(r"\b(fix|broken|error|crash|fails?|not working)\b", re.IGNORECASE)),
    ("causal_why", re.compile(r"\b(why|root cause|how did|what caused)\b", re.IGNORECASE)),
    ("add_test",   re.compile(r"\b(test|coverage|spec)\b", re.IGNORECASE)),
    ("refactor",   re.compile(r"\b(refactor|clean ?up|simplify)\b", re.IGNORECASE)),
    ("explain",    re.compile(r"\b(explain|walk me through|what does|how does)\b", re.IGNORECASE)),
]

_MAX_MSGS = 200  # guard pathological transcripts


def classify(message: str) -> str | None:
    for tag, pattern in INTENT_PATTERNS:
        if pattern.search(message):
            return tag
    return None


def collect_transitions(user_messages: list[str]) -> list[tuple[str, str]]:
    """Distinct adjacent intent-tag transitions within one session's user messages.

    Only the user's own messages are classified, so a followup can never be
    something Claude volunteered — it is always something the user typed next.

    Duplicates within a session are dropped: the analyzer counts distinct
    sessions per transition, so within-session repeats carry no signal and
    would only bloat the stored line. This bounds each line to at most
    len(vocabulary) * (len(vocabulary) - 1) = 20 pairs.
    """
    tags = [tag for message in user_messages[:_MAX_MSGS] if (tag := classify(message))]
    seen: set[tuple[str, str]] = set()
    distinct: list[tuple[str, str]] = []
    for i in range(len(tags) - 1):
        if tags[i] == tags[i + 1]:
            continue
        pair = (tags[i], tags[i + 1])
        if pair not in seen:
            seen.add(pair)
            distinct.append(pair)
    return distinct


def append_observation(
    transitions: list[tuple[str, str]],
    session_id: str,
    project: str,
    now: str,
    store: Path,
) -> None:
    if not transitions:
        return
    store.mkdir(parents=True, exist_ok=True)
    line = json.dumps({
        "session_id": session_id,
        "project": project,
        "ts": now,
        "transitions": [list(t) for t in transitions],
    })
    jsonl_path = store / "request_patterns.jsonl"
    lock_path = store / ".rp.lock"
    with FileLock(lock_path):
        with jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        _compact(jsonl_path)


def _compact(jsonl_path: Path) -> None:
    try:
        lines = jsonl_path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= _MAX_LINES:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)
        kept: list[str] = []
        for line in lines:
            try:
                record = json.loads(line)
                ts = datetime.fromisoformat(record.get("ts", ""))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    kept.append(line)
            except Exception:
                kept.append(line)
        jsonl_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    except Exception:
        pass
