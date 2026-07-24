"""Deterministic data collection. No scoring, no NLP, no analysis.

Everything here scrapes raw signals (user messages, tool calls, shell
history) and hands them to the harness, which lets Claude do the
actual synthesis.
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from filelock import FileLock

MAX_LINE_BYTES = 2 * 1024 * 1024  # skip pathological jsonl lines > 2MB
MAX_PROCESSED_SESSIONS = 500
SHELL_HISTORY_LIMIT = 200
LOCK_TIMEOUT_SECONDS = 10

# A transcript modified more recently than this is treated as belonging
# to a still-in-progress session and is NOT harvested. Stop hooks fire
# on every turn, so without a settle window session B's Stop hook could
# process (and permanently mark processed) session A's transcript after
# A's first turn, silently dropping all of A's later turns.
TRANSCRIPT_SETTLE_SECONDS = 15 * 60

DEFAULT_STORE = Path("~/.agent-persona").expanduser()
PERSONA_PATH = DEFAULT_STORE / "persona.md"

# User-message lines containing any of these markers are harness noise,
# not real user input.
_NOISE_MARKERS = (
    "<system-reminder",
    "<command-name>",
    "<local-command-stdout>",
    "Stop hook feedback:",
    "[Silent background task",
    "This session is being continued",
)

_ZSH_TIMESTAMP_RE = re.compile(r"^: \d+:\d+;")

_FILE_TOOLS = ("Read", "Write", "Edit")

# Secret patterns redacted from every data stream (shell history, Bash
# tool signals from transcripts, and user messages) before anything is
# ever sent to the API. Order matters: flag-value pairs are handled
# first so the flag name is preserved, then broader key=value and
# bare-token forms.
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(--token|--password|--api-key|--secret)\s+\S+"), r"\1 [REDACTED]"),
    (
        re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|auth)\s*[=:]\s*\S+"),
        "[REDACTED]",
    ),
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "[REDACTED]"),
    (re.compile(r"ghp_[a-zA-Z0-9]{36,}"), "[REDACTED]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED]"),
)


def _redact_secrets(text: str) -> str:
    """Strip API keys, tokens, and passwords from a piece of text."""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ---------------------------------------------------------------------------
# State store
# ---------------------------------------------------------------------------


def _state_path(state_store: Path) -> Path:
    return state_store / "state.json"


def _lock_path(state_store: Path) -> Path:
    return state_store / ".state.lock"


def _load_state(state_store: Path) -> dict:
    path = _state_path(state_store)
    if not path.exists():
        return {"processed_sessions": []}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"processed_sessions": []}
    if not isinstance(state, dict):
        return {"processed_sessions": []}
    if not isinstance(state.get("processed_sessions"), list):
        state["processed_sessions"] = []
    return state


def _write_state(state_store: Path, state: dict) -> None:
    state_store.mkdir(parents=True, exist_ok=True)
    tmp = _state_path(state_store).with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(_state_path(state_store))


def mark_processed(session_id: str, state_store: Path) -> None:
    """Record a session ID as processed, capping the list at 500 entries."""
    state_store.mkdir(parents=True, exist_ok=True)
    with FileLock(_lock_path(state_store), timeout=LOCK_TIMEOUT_SECONDS):
        state = _load_state(state_store)
        processed: list = state["processed_sessions"]
        if session_id not in processed:
            processed.append(session_id)
        state["processed_sessions"] = processed[-MAX_PROCESSED_SESSIONS:]
        state["last_run"] = datetime.now(UTC).isoformat()
        _write_state(state_store, state)


# ---------------------------------------------------------------------------
# Transcripts
# ---------------------------------------------------------------------------


def find_unprocessed_transcripts(
    claude_dir: Path,
    state_store: Path,
    exclude_session_id: str | None = None,
    settle_seconds: float = TRANSCRIPT_SETTLE_SECONDS,
) -> list[Path]:
    """Return transcript paths under claude_dir/projects not yet processed.

    Skips subagent transcripts, sessions already recorded in
    state_store/state.json, the currently in-progress session identified
    by exclude_session_id (when given), and any transcript modified
    within the last ``settle_seconds`` seconds. The settle window
    prevents one session's Stop hook from harvesting — and permanently
    marking processed — another session that is still mid-conversation,
    which would silently drop all of that session's later turns.
    """
    projects_dir = claude_dir / "projects"
    if not projects_dir.is_dir():
        return []

    processed = set(_load_state(state_store).get("processed_sessions", []))
    now = time.time()

    transcripts: list[Path] = []
    for path in sorted(projects_dir.rglob("*.jsonl")):
        if "/subagents/" in path.as_posix():
            continue
        if path.stem in processed:
            continue
        if exclude_session_id is not None and path.stem == exclude_session_id:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        # Recently-written transcripts may belong to concurrent
        # in-progress sessions; only harvest settled ones.
        if now - mtime < settle_seconds:
            continue
        transcripts.append(path)
    return transcripts


def _extract_text(content) -> str:
    """Pull plain text out of a message content field (str or block list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def _extract_tool_signals(content) -> list[str]:
    """Pull file paths and bash commands from tool_use blocks.

    Bash commands are redacted before they leave this function so
    secrets that Claude executed (curl auth headers, exported keys)
    never reach the API.
    """
    signals: list[str] = []
    if not isinstance(content, list):
        return signals
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        name = block.get("name", "")
        tool_input = block.get("input", {})
        if not isinstance(tool_input, dict):
            continue
        if name in _FILE_TOOLS:
            file_path = tool_input.get("file_path", "")
            if isinstance(file_path, str) and file_path:
                signals.append(f"{name}: {file_path}")
        elif name == "Bash":
            command = tool_input.get("command", "")
            if isinstance(command, str) and command:
                signals.append(f"Bash: {_redact_secrets(command)}")
    return signals


def collect_transcript(path: Path) -> tuple[list[str], list[str]]:
    """Parse one session transcript into (user_messages, tool_signals).

    Both streams are secret-redacted at collection time: user messages
    may contain pasted API keys, and Bash tool signals may contain
    tokens in executed commands.
    """
    user_messages: list[str] = []
    tool_signals: list[str] = []

    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return user_messages, tool_signals

    with handle:
        for line in handle:
            if len(line.encode("utf-8", errors="replace")) > MAX_LINE_BYTES:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue

            message = record.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")

            if message.get("role") == "user" and not record.get("isMeta"):
                text = _extract_text(content).strip()
                if any(marker in text for marker in _NOISE_MARKERS):
                    continue
                if text:
                    user_messages.append(_redact_secrets(text))

            tool_signals.extend(_extract_tool_signals(content))

    return user_messages, tool_signals


# ---------------------------------------------------------------------------
# Shell history
# ---------------------------------------------------------------------------


def collect_shell_history() -> list[str]:
    """Return the last 200 shell commands from zsh or bash history.

    Secrets (API keys, tokens, passwords) are redacted before the
    commands leave this function.
    """
    home = Path.home()
    for candidate in (home / ".zsh_history", home / ".bash_history"):
        if not candidate.exists():
            continue
        try:
            raw = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        commands: list[str] = []
        for line in raw.splitlines():
            line = _ZSH_TIMESTAMP_RE.sub("", line).strip()
            if line:
                commands.append(_redact_secrets(line))
        return commands[-SHELL_HISTORY_LIMIT:]
    return []
