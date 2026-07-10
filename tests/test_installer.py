from __future__ import annotations

import json
from pathlib import Path

from agent_persona import installer


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _legacy_settings() -> dict:
    """settings.json as a 0.3.x install left it, plus one user hook."""
    return {
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python -m agent_persona.hooks.session_start_hook",
                        }
                    ]
                }
            ],
            "Stop": [
                {"hooks": [{"type": "command", "command": "python -m agent_persona.hooks.stop_hook"}]},
                {"hooks": [{"type": "command", "command": "echo user-hook"}]},
            ],
            "PostToolUse": [
                {
                    "matcher": "Write|Edit",
                    "hooks": [{"type": "command", "command": "python -m agent_persona.hooks.file_hook"}],
                }
            ],
        },
        "model": "opus",
    }


class TestStopHook:
    def test_install_adds_hook(self, tmp_path):
        settings = tmp_path / "settings.json"
        assert installer.install_stop_hook(settings) is True
        entries = _read(settings)["hooks"]["Stop"]
        assert any(installer._is_our_hook(e) for e in entries)

    def test_install_is_idempotent(self, tmp_path):
        settings = tmp_path / "settings.json"
        installer.install_stop_hook(settings)
        assert installer.install_stop_hook(settings) is False
        assert len(_read(settings)["hooks"]["Stop"]) == 1

    def test_uninstall_removes_only_ours(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text(
            json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}),
            encoding="utf-8",
        )
        installer.install_stop_hook(settings)
        assert installer.uninstall_stop_hook(settings) is True
        entries = _read(settings)["hooks"]["Stop"]
        assert entries == [{"hooks": [{"type": "command", "command": "echo mine"}]}]

    def test_installed_detection(self, tmp_path):
        settings = tmp_path / "settings.json"
        assert installer.stop_hook_installed(settings) is False
        installer.install_stop_hook(settings)
        assert installer.stop_hook_installed(settings) is True

    def test_invalid_json_is_left_alone(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text("{broken", encoding="utf-8")
        assert installer.install_stop_hook(settings) is False
        assert settings.read_text(encoding="utf-8") == "{broken"


class TestLegacyMigration:
    def test_install_strips_all_legacy_hooks_keeps_user_hooks(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps(_legacy_settings()), encoding="utf-8")

        assert installer.install_stop_hook(settings) is True

        result = _read(settings)
        hooks = result["hooks"]
        assert "SessionStart" not in hooks
        assert "PostToolUse" not in hooks
        commands = [h["command"] for e in hooks["Stop"] for h in e["hooks"]]
        assert "echo user-hook" in commands
        assert not any("stop_hook" in c or "session_start" in c or "file_hook" in c for c in commands)
        assert any(c.endswith("agent_persona.hooks.stop") for c in commands)
        assert result["model"] == "opus"  # untouched non-hook settings

    def test_legacy_stop_hook_not_mistaken_for_new(self, tmp_path):
        entry = {"hooks": [{"type": "command", "command": "python -m agent_persona.hooks.stop_hook"}]}
        assert installer._is_legacy_hook(entry) is True
        assert installer._is_our_hook(entry) is False

    def test_legacy_prompt_hook_detected(self):
        entry = {"hooks": [{"type": "prompt", "prompt": "read ~/.agent-persona/profile.json"}]}
        assert installer._is_legacy_hook(entry) is True

    def test_legacy_hooks_present(self, tmp_path):
        settings = tmp_path / "settings.json"
        assert installer.legacy_hooks_present(settings) is False
        settings.write_text(json.dumps(_legacy_settings()), encoding="utf-8")
        assert installer.legacy_hooks_present(settings) is True
        installer.install_stop_hook(settings)
        assert installer.legacy_hooks_present(settings) is False


class TestClaudeMdBind:
    def test_bind_appends_marker_block(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# My rules\n", encoding="utf-8")
        persona = tmp_path / "persona.md"

        assert installer.bind(persona, claude_md) is True
        content = claude_md.read_text(encoding="utf-8")
        assert content.startswith("# My rules\n")
        assert f"@{persona}" in content
        assert installer.is_bound(claude_md) is True

    def test_bind_is_idempotent(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        persona = tmp_path / "persona.md"
        installer.bind(persona, claude_md)
        assert installer.bind(persona, claude_md) is False

    def test_unbind_removes_only_marker_block(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Keep me\n\nAnd me.\n", encoding="utf-8")
        persona = tmp_path / "persona.md"
        installer.bind(persona, claude_md)

        assert installer.unbind(claude_md) is True
        content = claude_md.read_text(encoding="utf-8")
        assert "# Keep me" in content and "And me." in content
        assert "agent-persona" not in content
        assert installer.is_bound(claude_md) is False

    def test_unbind_without_binding(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Untouched\n", encoding="utf-8")
        assert installer.unbind(claude_md) is False
        assert claude_md.read_text(encoding="utf-8") == "# Untouched\n"
