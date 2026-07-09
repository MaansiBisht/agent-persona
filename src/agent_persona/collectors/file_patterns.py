from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import reduce
from math import gcd
from pathlib import Path

_ROLLING_DAYS = 90
_MAX_FILES_FOR_INDENT = 10
_INDENT_LINES = 50


def collect_file_signals(store: Path) -> dict:
    log_path = store / "history" / "files_edited.jsonl"
    cutoff = datetime.now(timezone.utc) - timedelta(days=_ROLLING_DAYS)

    extensions: dict[str, int] = {}
    paths: list[str] = []
    test_file_count = 0

    indent_votes: list[tuple[str, int]] = []

    if log_path.exists():
        with log_path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw_line in fh:
                try:
                    entry = json.loads(raw_line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(entry, dict):
                    continue
                ts_raw = entry.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_raw)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts < cutoff:
                        continue
                except (ValueError, TypeError):
                    continue
                ext = entry.get("ext", "")
                if isinstance(ext, str) and ext:
                    key = ext.lstrip(".")
                    extensions[key] = extensions.get(key, 0) + 1
                path = entry.get("path", "")
                if isinstance(path, str) and path:
                    paths.append(path)
                    name = Path(path).name.lower()
                    if "test" in name or "spec" in name:
                        test_file_count += 1
                # use indent captured at write time if available
                if entry.get("indent") and entry["indent"] != "unknown":
                    indent_votes.append((entry["indent"], int(entry.get("indent_size", 4))))

    total_file_count = len(paths)
    indent, indent_size = _vote_indent(indent_votes) if indent_votes else _detect_indent(paths)

    return {
        "extensions": extensions,
        "indent": indent,
        "indent_size": indent_size,
        "test_file_count": test_file_count,
        "total_file_count": total_file_count,
    }


def _vote_indent(votes: list[tuple[str, int]]) -> tuple[str, int]:
    spaces = [(style, size) for style, size in votes if style == "spaces"]
    tabs = [(style, size) for style, size in votes if style == "tabs"]
    if len(tabs) > len(spaces):
        return "tabs", 4
    if spaces:
        sizes = [size for _, size in spaces]
        most_common = max(set(sizes), key=sizes.count)
        return "spaces", most_common
    return "unknown", 4


def _detect_indent(paths: list[str]) -> tuple[str, int]:
    space_count = 0
    tab_count = 0
    indent_sizes: list[int] = []

    sample = paths[-_MAX_FILES_FOR_INDENT:] if len(paths) > _MAX_FILES_FOR_INDENT else paths

    for path_str in sample:
        try:
            lines = _read_first_lines(Path(path_str), _INDENT_LINES)
        except OSError:
            continue
        for line in lines:
            if line.startswith("\t"):
                tab_count += 1
            elif line.startswith(" "):
                space_count += 1
                leading = len(line) - len(line.lstrip(" "))
                if leading > 0:
                    indent_sizes.append(leading)

    if space_count == 0 and tab_count == 0:
        return "unknown", 4

    if tab_count > space_count:
        return "tabs", 4

    size = _smallest_indent_unit(indent_sizes) if indent_sizes else 4
    return "spaces", size


def _read_first_lines(path: Path, n: int) -> list[str]:
    lines: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if i >= n:
                break
            lines.append(line)
    return lines


def _smallest_indent_unit(sizes: list[int]) -> int:
    # GCD of observed indent levels reveals the base unit (e.g. 2 or 4 spaces)
    non_zero = [s for s in sizes if s > 0]
    if not non_zero:
        return 4
    result = reduce(gcd, non_zero)
    return result if result > 0 else 4
