from __future__ import annotations

import json
from pathlib import Path


from agent_persona.installer import _build_hooks, install, is_installed, uninstall


# ── helpers ──────────────────────────────────────────────────────────────────


def _settings_path(tmp_path: Path) -> Path:
    return tmp_path / "settings.json"


def _read_settings(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ── install ───────────────────────────────────────────────────────────────────


def test_install_into_missing_settings_creates_file_with_hooks(tmp_path: Path) -> None:
    """install() creates settings.json with the agent-persona hooks when the file is absent."""
    settings = _settings_path(tmp_path)

    install(settings_path=settings)

    assert settings.exists()
    data = _read_settings(settings)
    assert "hooks" in data
    hook_events = set(data["hooks"].keys())
    assert hook_events & set(_build_hooks().keys())


def test_install_twice_is_idempotent(tmp_path: Path) -> None:
    """install() does not add duplicate hooks when called a second time."""
    from agent_persona.installer import _is_ours

    settings = _settings_path(tmp_path)

    install(settings_path=settings)
    install(settings_path=settings)

    data = _read_settings(settings)
    for event, entries in data["hooks"].items():
        ap_count = sum(1 for e in entries if _is_ours(e))
        expected = sum(1 for e in _build_hooks().get(event, []) if _is_ours(e))
        assert ap_count == expected


def test_is_installed_returns_true_after_install(tmp_path: Path) -> None:
    """is_installed() returns True immediately after install()."""
    settings = _settings_path(tmp_path)

    install(settings_path=settings)

    assert is_installed(settings_path=settings) is True


def test_uninstall_removes_hooks_from_settings(tmp_path: Path) -> None:
    """uninstall() removes all agent-persona hooks from settings.json."""
    settings = _settings_path(tmp_path)
    install(settings_path=settings)

    uninstall(settings_path=settings)

    from agent_persona.installer import _is_ours

    data = _read_settings(settings)
    for entries in data.get("hooks", {}).values():
        for entry in entries:
            assert not _is_ours(entry)


def test_is_installed_returns_false_after_uninstall(tmp_path: Path) -> None:
    """is_installed() returns False after uninstall() removes all hooks."""
    settings = _settings_path(tmp_path)
    install(settings_path=settings)
    uninstall(settings_path=settings)

    assert is_installed(settings_path=settings) is False


def test_install_preserves_existing_unrelated_hooks(tmp_path: Path) -> None:
    """install() does not remove pre-existing hooks that do not belong to agent-persona."""
    settings = _settings_path(tmp_path)
    existing = {
        "hooks": {
            "PostToolUse": [
                {
                    "type": "command",
                    "command": "pnpm prettier --write",
                    "description": "format on save",
                }
            ]
        }
    }
    settings.write_text(json.dumps(existing), encoding="utf-8")

    install(settings_path=settings)

    data = _read_settings(settings)
    post_tool_entries = data["hooks"].get("PostToolUse", [])
    descriptions = [e.get("description", "") for e in post_tool_entries]
    assert "format on save" in descriptions


def test_install_structure_is_valid_json_with_hooks_key(tmp_path: Path) -> None:
    """The settings file produced by install() is valid JSON with a 'hooks' key."""
    settings = _settings_path(tmp_path)

    install(settings_path=settings)

    raw = settings.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert isinstance(data.get("hooks"), dict)


def test_install_uses_matcher_hooks_array_structure(tmp_path: Path) -> None:
    """Each event entry must be a wrapper with a 'hooks' array (current schema),
    not a flat object with type/command at the top level."""
    settings = _settings_path(tmp_path)

    install(settings_path=settings)

    data = _read_settings(settings)
    for event, entries in data["hooks"].items():
        for entry in entries:
            assert isinstance(entry.get("hooks"), list), f"{event} entry missing hooks array"
            assert "type" not in entry, f"{event} entry has top-level type (old format)"
            for hook in entry["hooks"]:
                assert "type" in hook


def test_is_installed_returns_false_when_settings_missing(tmp_path: Path) -> None:
    """is_installed() returns False when settings.json does not exist."""
    settings = _settings_path(tmp_path)

    assert is_installed(settings_path=settings) is False
