from __future__ import annotations

import json
import sys
from pathlib import Path

from filelock import FileLock


def _build_hooks() -> dict[str, list[dict]]:
    py = sys.executable
    return {
        "SessionStart": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": f"{py} -m agent_persona.hooks.session_start_hook",
                        "timeout": 5,
                    }
                ]
            }
        ],
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": f"{py} -m agent_persona.hooks.stop_hook",
                    }
                ]
            }
        ],
        "PostToolUse": [
            {
                "matcher": "Write|Edit",
                "hooks": [
                    {
                        "type": "command",
                        "command": f"{py} -m agent_persona.hooks.file_hook",
                    }
                ]
            }
        ],
    }


# Hooks are identified as ours by their command/prompt content, not by a
# non-schema "description" field. The command always references the package
# module path; the prompt hook references the profile store path.
_CMD_MARKER = "agent_persona.hooks"
_PROMPT_MARKER = "~/.agent-persona/profile.json"


def _default_settings_path() -> Path:
    return Path("~/.claude/settings.json").expanduser()


def _is_ours(entry: dict) -> bool:
    """True if a hook-matcher wrapper entry was created by agent-persona."""
    if not isinstance(entry, dict):
        return False
    for hook in entry.get("hooks", []):
        if not isinstance(hook, dict):
            continue
        command = hook.get("command", "")
        prompt = hook.get("prompt", "")
        if isinstance(command, str) and _CMD_MARKER in command:
            return True
        if isinstance(prompt, str) and _PROMPT_MARKER in prompt:
            return True
    return False


def _hooks_present(settings: dict) -> bool:
    hooks_section = settings.get("hooks", {})
    for event_hooks in hooks_section.values():
        if isinstance(event_hooks, list):
            for entry in event_hooks:
                if _is_ours(entry):
                    return True
    return False


def install(settings_path: Path | None = None, store: Path | None = None) -> bool:
    path = settings_path or _default_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    lock_path = path.parent / ".settings.lock"
    with FileLock(lock_path):
        raw = path.read_text(encoding="utf-8").strip() if path.exists() else ""
        settings: dict = {}
        if raw:
            try:
                settings = json.loads(raw)
            except json.JSONDecodeError as exc:
                print(f"agent-persona: error: {path} contains invalid JSON: {exc}", file=sys.stderr)
                return False

        if _hooks_present(settings):
            return False

        hooks_section: dict = settings.setdefault("hooks", {})
        for event, entries in _build_hooks().items():
            existing: list = hooks_section.setdefault(event, [])
            existing.extend(entries)

        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        tmp.rename(path)

    return True


def uninstall(settings_path: Path | None = None) -> bool:
    path = settings_path or _default_settings_path()
    if not path.exists():
        return False

    lock_path = path.parent / ".settings.lock"
    with FileLock(lock_path):
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return False
        try:
            settings = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"agent-persona: error: {path} contains invalid JSON: {exc}", file=sys.stderr)
            return False

        hooks_section = settings.get("hooks", {})
        removed = False
        for event in list(hooks_section.keys()):
            original = hooks_section[event]
            filtered = [e for e in original if not _is_ours(e)]
            if len(filtered) != len(original):
                removed = True
            if filtered:
                hooks_section[event] = filtered
            else:
                del hooks_section[event]

        if not removed:
            return False

        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        tmp.rename(path)

    return True


def is_installed(settings_path: Path | None = None) -> bool:
    path = settings_path or _default_settings_path()
    if not path.exists():
        return False
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return _hooks_present(settings)
