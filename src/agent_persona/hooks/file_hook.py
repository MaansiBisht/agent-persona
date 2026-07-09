from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


_BLOCKED_SUBSTRINGS = ("password", "secret", ".env", ".key", "credentials")
_MAX_LINES = 2000
_RETENTION_DAYS = 90


def _is_blocked(path: str) -> bool:
    lower = path.lower()
    return any(sub in lower for sub in _BLOCKED_SUBSTRINGS)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
                ts = datetime.fromisoformat(record.get("timestamp", ""))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    kept.append(line)
            except Exception:
                kept.append(line)
        jsonl_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    except Exception:
        pass


def _sample_indent(path: str) -> tuple[str, int]:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[:50]
        spaces = sum(1 for ln in lines if ln.startswith(" "))
        tabs = sum(1 for ln in lines if ln.startswith("\t"))
        if tabs > spaces:
            return "tabs", 4
        if spaces > 0:
            sizes = [len(ln) - len(ln.lstrip(" ")) for ln in lines if ln.startswith(" ")]
            non_zero = [s for s in sizes if s > 0]
            if non_zero:
                from math import gcd
                from functools import reduce
                unit = reduce(gcd, non_zero)
                return "spaces", unit if unit > 0 else 4
            return "spaces", 4
    except OSError:
        pass
    return "unknown", 4


def main() -> None:
    try:
        file_path: str | None = None

        raw = sys.stdin.read().strip()
        if raw:
            try:
                data = json.loads(raw)
                file_path = data.get("tool_input", {}).get("file_path")
            except (json.JSONDecodeError, AttributeError):
                pass

        if not file_path and len(sys.argv) > 1:
            file_path = sys.argv[1]

        if not file_path:
            return

        abs_path = str(Path(file_path).resolve())

        if _is_blocked(abs_path):
            return
        ext = Path(file_path).suffix

        from agent_persona.profile import default_store

        store = default_store()
        history_dir = store / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = history_dir / "files_edited.jsonl"

        indent, indent_size = _sample_indent(abs_path)
        record = json.dumps({
            "path": abs_path,
            "ext": ext,
            "timestamp": _now_iso(),
            "indent": indent,
            "indent_size": indent_size,
        })
        with open(jsonl_path, "a", encoding="utf-8") as fh:
            fh.write(record + "\n")

        _compact(jsonl_path)
    except Exception:
        pass


if __name__ == "__main__":
    main()
