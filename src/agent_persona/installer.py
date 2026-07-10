"""Two independent concerns:

1. Stop hook  — writes to ~/.claude/settings.json so persona.md is
   regenerated automatically when a session ends.

2. CLAUDE.md bind — writes a single @import line into ~/.claude/CLAUDE.md
   so Claude natively reads persona.md at every session start.
   No stdout tricks. No SessionStart hook. Just Claude's own mechanism.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from filelock import FileLock

LOCK_TIMEOUT = 10

_CLAUDE_DIR = Path("~/.claude").expanduser()
_SETTINGS_PATH = _CLAUDE_DIR / "settings.json"
_CLAUDE_MD_PATH = _CLAUDE_DIR / "CLAUDE.md"

_MARKER_START = "<!-- agent-persona:start -->"
_MARKER_END = "<!-- agent-persona:end -->"
_CMD_MARKER = "agent_persona.hooks.stop"

# 0.3.x hooks point at modules deleted in 0.4.0 and would error on every
# session; install strips them. _CMD_MARKER is a substring of the legacy
# stop_hook module, so ours is matched by exact suffix, not substring.
_LEGACY_CMD_MODULES = (
    "agent_persona.hooks.session_start_hook",
    "agent_persona.hooks.stop_hook",
    "agent_persona.hooks.file_hook",
)
_LEGACY_PROMPT_MARKER = "~/.agent-persona/profile.json"


# ── Stop hook ─────────────────────────────────────────────────────────────────

def _stop_hook_entry() -> dict:
    return {
        "hooks": [
            {
                "type": "command",
                "command": f"{sys.executable} -m agent_persona.hooks.stop",
                "timeout": 30,
            }
        ]
    }


def _is_our_hook(entry: dict) -> bool:
    if not isinstance(entry, dict):
        return False
    for hook in entry.get("hooks", []):
        if isinstance(hook, dict) and hook.get("command", "").rstrip().endswith(_CMD_MARKER):
            return True
    return False


def _is_legacy_hook(entry: dict) -> bool:
    """True for hook entries left behind by a 0.3.x install."""
    if not isinstance(entry, dict):
        return False
    for hook in entry.get("hooks", []):
        if not isinstance(hook, dict):
            continue
        command = hook.get("command", "")
        prompt = hook.get("prompt", "")
        if isinstance(command, str) and any(m in command for m in _LEGACY_CMD_MODULES):
            return True
        if isinstance(prompt, str) and _LEGACY_PROMPT_MARKER in prompt:
            return True
    return False


def _strip_legacy_hooks(settings: dict) -> bool:
    """Remove 0.3.x hook entries in place. Returns True if any were removed."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False
    removed = False
    for event in list(hooks.keys()):
        entries = hooks[event]
        if not isinstance(entries, list):
            continue
        filtered = [e for e in entries if not _is_legacy_hook(e)]
        if len(filtered) != len(entries):
            removed = True
            if filtered:
                hooks[event] = filtered
            else:
                del hooks[event]
    return removed


def legacy_hooks_present(settings_path: Path = _SETTINGS_PATH) -> bool:
    """True if stale 0.3.x hook entries remain in settings.json."""
    if not settings_path.exists():
        return False
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(settings, dict):
        return False
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        return False
    return any(
        isinstance(entries, list) and any(_is_legacy_hook(e) for e in entries)
        for entries in hooks.values()
    )


def _stop_hook_present(settings: dict) -> bool:
    for entries in settings.get("hooks", {}).values():
        if isinstance(entries, list) and any(_is_our_hook(e) for e in entries):
            return True
    return False


def install_stop_hook(settings_path: Path = _SETTINGS_PATH) -> bool:
    """Add the Stop hook to settings.json, stripping stale 0.3.x hooks.

    Returns True if anything changed (hook added or legacy removed).
    """
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    lock = settings_path.parent / ".settings.lock"
    with FileLock(lock, timeout=LOCK_TIMEOUT):
        raw = settings_path.read_text(encoding="utf-8").strip() if settings_path.exists() else ""
        try:
            settings = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return False
        if not isinstance(settings, dict):
            settings = {}
        if not isinstance(settings.get("hooks"), dict):
            settings["hooks"] = {}
        legacy_removed = _strip_legacy_hooks(settings)
        if _stop_hook_present(settings) and not legacy_removed:
            return False
        if not _stop_hook_present(settings):
            stop_list = settings["hooks"].setdefault("Stop", [])
            if not isinstance(stop_list, list):
                settings["hooks"]["Stop"] = []
                stop_list = settings["hooks"]["Stop"]
            stop_list.append(_stop_hook_entry())
        tmp = settings_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        tmp.replace(settings_path)
    return True


def uninstall_stop_hook(settings_path: Path = _SETTINGS_PATH) -> bool:
    """Remove the Stop hook from settings.json. Returns True if removed."""
    if not settings_path.exists():
        return False
    lock = settings_path.parent / ".settings.lock"
    with FileLock(lock, timeout=LOCK_TIMEOUT):
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        if not isinstance(settings, dict):
            return False
        hooks = settings.get("hooks", {})
        if not isinstance(hooks, dict):
            return False
        removed = False
        for event in list(hooks.keys()):
            original = hooks[event]
            if not isinstance(original, list):
                continue
            filtered = [e for e in original if not (_is_our_hook(e) or _is_legacy_hook(e))]
            if len(filtered) != len(original):
                removed = True
            if filtered:
                hooks[event] = filtered
            elif removed:
                del hooks[event]
        if not removed:
            return False
        tmp = settings_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        tmp.replace(settings_path)
    return True


def stop_hook_installed(settings_path: Path = _SETTINGS_PATH) -> bool:
    if not settings_path.exists():
        return False
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        return isinstance(settings, dict) and _stop_hook_present(settings)
    except (json.JSONDecodeError, OSError):
        return False


# ── CLAUDE.md bind ────────────────────────────────────────────────────────────

def _import_block(persona_path: Path) -> str:
    return f"{_MARKER_START}\n@{persona_path}\n{_MARKER_END}\n"


def bind(persona_path: Path, claude_md: Path = _CLAUDE_MD_PATH) -> bool:
    """Append @import block to CLAUDE.md. Returns True if newly added."""
    claude_md.parent.mkdir(parents=True, exist_ok=True)
    lock = claude_md.parent / ".claude-md.lock"
    with FileLock(lock, timeout=LOCK_TIMEOUT):
        existing = claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""
        if _MARKER_START in existing:
            return False  # already bound
        block = _import_block(persona_path)
        separator = "\n" if existing and not existing.endswith("\n") else ""
        tmp = claude_md.with_suffix(".tmp")
        tmp.write_text(existing + separator + block, encoding="utf-8")
        tmp.replace(claude_md)
    return True


def unbind(claude_md: Path = _CLAUDE_MD_PATH) -> bool:
    """Remove @import block from CLAUDE.md. Returns True if removed."""
    if not claude_md.exists():
        return False
    lock = claude_md.parent / ".claude-md.lock"
    with FileLock(lock, timeout=LOCK_TIMEOUT):
        content = claude_md.read_text(encoding="utf-8")
        pattern = rf"\n?{re.escape(_MARKER_START)}.*?{re.escape(_MARKER_END)}\n?"
        new_content, n = re.subn(pattern, "", content, flags=re.DOTALL)
        if not n:
            return False
        tmp = claude_md.with_suffix(".tmp")
        tmp.write_text(new_content, encoding="utf-8")
        tmp.replace(claude_md)
    return True


def is_bound(claude_md: Path = _CLAUDE_MD_PATH) -> bool:
    if not claude_md.exists():
        return False
    try:
        return _MARKER_START in claude_md.read_text(encoding="utf-8")
    except OSError:
        return False


# ── Convenience: install / uninstall both at once ─────────────────────────────

def install(persona_path: Path) -> dict[str, bool]:
    """Install Stop hook + bind CLAUDE.md. Returns what was newly added."""
    return {
        "stop_hook": install_stop_hook(),
        "claude_md": bind(persona_path),
    }


def uninstall() -> dict[str, bool]:
    """Remove Stop hook + unbind CLAUDE.md. Returns what was removed."""
    return {
        "stop_hook": uninstall_stop_hook(),
        "claude_md": unbind(),
    }
