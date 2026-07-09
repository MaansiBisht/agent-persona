from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

_SUBAGENT_PATTERN = re.compile(r"/subagents/")
_MAX_LINE_BYTES = 2 * 1024 * 1024
_STATE_CAP = 500

# Markers that identify system-injected content masquerading as user turns:
# slash-command wrappers, command output, hook feedback, caveats, and the
# CLAUDE.md / system-reminder context. Preferences and request patterns must
# never be extracted from these — only from text the human actually typed.
_INJECTION_MARKERS = (
    "<system-reminder",
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<local-command-stdout>",
    "<local-command-caveat>",
    "<bash-input>",
    "<bash-stdout>",
    "<bash-stderr>",
    "Caveat: The messages below",
    "Stop hook feedback:",
    "[Silent background task",
    "[Request interrupted by user]",
    "This session is being continued",
)


def _is_injected(text: str) -> bool:
    return any(marker in text for marker in _INJECTION_MARKERS)


def find_unprocessed_transcripts(
    claude_dir: Path = Path("~/.claude").expanduser(),
    state_store: Path | None = None,
) -> list[Path]:
    if state_store is None:
        raise ValueError("state_store is required")
    state = _load_state(state_store)
    processed: set[str] = set(state.get("processed_sessions", []))
    transcripts_dir = claude_dir / "projects"
    if not transcripts_dir.exists():
        return []
    candidates: list[Path] = []
    for path in transcripts_dir.rglob("*.jsonl"):
        if _SUBAGENT_PATTERN.search(str(path)):
            continue
        session_id = path.stem
        if session_id not in processed:
            candidates.append(path)
    return candidates


def collect_transcript(
    transcript_path: Path,
    state_store: Path,
) -> tuple[list[str], list[str]]:
    user_messages: list[str] = []
    tool_signals: list[str] = []

    with transcript_path.open("rb") as fh:
        for raw_line in fh:
            if len(raw_line) > _MAX_LINE_BYTES:
                continue
            try:
                record = json.loads(raw_line)
            except (json.JSONDecodeError, ValueError):
                continue
            _extract_record(record, user_messages, tool_signals)

    return user_messages, tool_signals


def _extract_record(
    record: object,
    user_messages: list[str],
    tool_signals: list[str],
) -> None:
    if not isinstance(record, dict):
        return
    message = record.get("message")
    if not isinstance(message, dict):
        return
    role = message.get("role")
    content = message.get("content")
    # Skip system-injected turns: meta records, and command/hook/reminder text
    # that the human did not actually type.
    if role == "user" and not record.get("isMeta"):
        if isinstance(content, str):
            if not _is_injected(content):
                user_messages.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if isinstance(text, str) and not _is_injected(text):
                        user_messages.append(text)
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            tool_name = block.get("name", "")
            inp = block.get("input", {})
            if not isinstance(inp, dict):
                continue
            if tool_name in ("Read", "Write", "Edit"):
                path_val = inp.get("file_path") or inp.get("path", "")
                if isinstance(path_val, str) and path_val:
                    tool_signals.append(path_val)
            elif tool_name == "Bash":
                cmd = inp.get("command", "")
                if isinstance(cmd, str) and cmd:
                    tool_signals.append(cmd)


def mark_processed(session_id: str, state_store: Path) -> None:
    state_file = state_store / "state.json"
    state_store.mkdir(parents=True, exist_ok=True)
    lock_path = state_store / ".state.lock"
    with FileLock(lock_path):
        raw = state_file.read_bytes() if state_file.exists() else b""
        state: dict = json.loads(raw) if raw else {}
        sessions: list[str] = state.get("processed_sessions", [])
        if session_id not in sessions:
            sessions.append(session_id)
        if len(sessions) > _STATE_CAP:
            sessions = sessions[-_STATE_CAP:]
        state["processed_sessions"] = sessions
        state["last_run"] = datetime.now(timezone.utc).isoformat()
        state_file.write_bytes(json.dumps(state).encode())


def _load_state(state_store: Path) -> dict:
    state_file = state_store / "state.json"
    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
