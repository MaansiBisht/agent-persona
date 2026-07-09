from __future__ import annotations

import re
from pathlib import Path

_ZSH_TIMESTAMP = re.compile(r"^: \d+:\d+;")
_HISTORY_FILES = [
    Path("~/.zsh_history"),
    Path("~/.bash_history"),
    Path("~/.histfile"),
]


def collect_shell_history(limit: int = 500) -> list[str]:
    history_file = _find_history_file()
    if history_file is None:
        return []
    lines = _tail_lines(history_file, limit * 2)
    cleaned = _clean_lines(lines)
    seen: dict[str, None] = {}
    for cmd in cleaned:
        seen[cmd] = None
    deduped = list(seen.keys())
    return deduped[-limit:]


def _find_history_file() -> Path | None:
    for candidate in _HISTORY_FILES:
        expanded = candidate.expanduser()
        if expanded.exists():
            return expanded
    return None


def _tail_lines(path: Path, n: int) -> list[str]:
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            chunk_size = min(size, n * 200)
            fh.seek(max(0, size - chunk_size))
            raw = fh.read()
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        return lines[-n:]
    except OSError:
        return []


def _clean_lines(lines: list[str]) -> list[str]:
    result: list[str] = []
    for line in lines:
        stripped = _ZSH_TIMESTAMP.sub("", line).strip()
        if stripped:
            result.append(stripped)
    return result
