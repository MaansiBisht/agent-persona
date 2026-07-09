from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from filelock import FileLock

from agent_persona.collectors.transcript import _MAX_LINE_BYTES, _is_injected

_RETENTION_DAYS = 90
_MAX_LINES = 2000
_MAX_TURNS = 400

# Closed correction taxonomy. High-precision corrective phrases only — we favor
# missing a correction over mislabeling normal speech (e.g. bare "no" is excluded
# because "no problem" / "no, that's fine" are not corrections).
CORRECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("revert",         re.compile(r"\b(revert|undo|roll\s?back|put it back|restore (it|the|that))\b", re.IGNORECASE)),
    ("simplify",       re.compile(r"\b(too complex|over[\s-]?engineer\w*|overkill|too much|keep it simple|simpler|simplif\w+)\b", re.IGNORECASE)),
    ("wrong_approach", re.compile(r"(not what i (asked|wanted|meant)|misunderstood|that'?s wrong|wrong approach|not right|off track)", re.IGNORECASE)),
    ("scope",          re.compile(r"(don'?t (add|do|create|change|touch)|not yet|only (do|change|touch)|no need to|stop (adding|doing|creating|changing))", re.IGNORECASE)),
    ("redo",           re.compile(r"(not like that|try again|redo (it|this|that)|that'?s not (it|what)|do it again)", re.IGNORECASE)),
]


def classify_correction(text: str) -> str | None:
    for kind, pattern in CORRECTION_PATTERNS:
        if pattern.search(text):
            return kind
    return None


def _user_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if isinstance(text, str):
                    return text
    return ""


def _assistant_action(content: object) -> str | None:
    """Strongest action in an assistant turn: edit > command > answer."""
    if not isinstance(content, list):
        return None
    saw_command = False
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        name = block.get("name", "")
        if name in ("Write", "Edit"):
            return "edit"
        if name == "Bash":
            saw_command = True
    return "command" if saw_command else None


def collect_correction_events(transcript_path: Path) -> list[tuple[str, str]]:
    """Walk the transcript in order and flag user turns that correct Claude.

    Returns a list of (kind, after) where `after` is the preceding Claude
    action — edit | command | answer. Only user turns that follow some Claude
    activity count, so a correction is always a reaction to something Claude did.
    """
    events: list[tuple[str, str]] = []
    pending_action: str | None = None  # strongest action since the last user turn
    seen_assistant = False
    turns = 0

    with transcript_path.open("rb") as fh:
        for raw in fh:
            if len(raw) > _MAX_LINE_BYTES:
                continue
            try:
                record = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(record, dict):
                continue
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            content = message.get("content")
            turns += 1
            if turns > _MAX_TURNS:
                break

            if role == "assistant":
                seen_assistant = True
                action = _assistant_action(content)
                if action == "edit" or (action == "command" and pending_action != "edit"):
                    pending_action = action
            elif role == "user" and not record.get("isMeta"):
                text = _user_text(content)
                if text and seen_assistant and not _is_injected(text):
                    kind = classify_correction(text)
                    if kind:
                        events.append((kind, pending_action or "answer"))
                pending_action = None

    return events


def append_corrections(
    events: list[tuple[str, str]],
    session_id: str,
    project: str,
    now: str,
    store: Path,
) -> None:
    if not events:
        return
    store.mkdir(parents=True, exist_ok=True)
    line = json.dumps({
        "session_id": session_id,
        "project": project,
        "ts": now,
        "corrections": [list(e) for e in events],
    })
    jsonl_path = store / "corrections.jsonl"
    with FileLock(store / ".corrections.lock"):
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
