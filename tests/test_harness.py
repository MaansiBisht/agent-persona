from __future__ import annotations

import json
from pathlib import Path

from agent_persona import collectors, harness


def _fake_transcripts(tmp_path: Path, names: list[str]) -> list[Path]:
    paths = []
    for name in names:
        p = tmp_path / f"{name}.jsonl"
        p.write_text("", encoding="utf-8")
        paths.append(p)
    return paths


def _patch_collection(monkeypatch, transcripts, messages=None, signals=None):
    monkeypatch.setattr(
        collectors, "find_unprocessed_transcripts", lambda **kw: transcripts
    )
    monkeypatch.setattr(
        collectors,
        "collect_transcript",
        lambda path: (messages or ["build me an api"], signals or ["Bash: ls"]),
    )
    monkeypatch.setattr(collectors, "collect_shell_history", lambda: ["git status"])


class TestBuildDataSummary:
    def test_includes_all_sections(self):
        summary = harness._build_data_summary(
            shell_commands=["ls"],
            user_messages=["hello"],
            tool_signals=["Read: /a.py"],
            session_count=1,
            existing_persona="## Developer Persona\nold",
        )
        assert "EXISTING PERSONA" in summary
        assert "SHELL COMMANDS" in summary
        assert "SESSION MESSAGES (1 sessions)" in summary
        assert "TOOL SIGNALS" in summary

    def test_truncates_oversized_messages(self):
        summary = harness._build_data_summary(
            shell_commands=[],
            user_messages=["x" * (harness.MAX_MESSAGES_CHARS + 1000)],
            tool_signals=[],
            session_count=1,
            existing_persona="",
        )
        assert "[...truncated]" in summary
        assert len(summary) <= harness.MAX_DATA_CHARS + 100


class TestRun:
    def test_success_writes_persona_and_marks_processed(self, tmp_path, monkeypatch):
        store = tmp_path / "store"
        persona = tmp_path / "persona.md"
        _patch_collection(monkeypatch, _fake_transcripts(tmp_path, ["s1", "s2"]))
        monkeypatch.setattr(harness, "_call_claude_cli", lambda prompt: "## Developer Persona\nok")

        status, message = harness.run(store=store, persona_path=persona)

        assert status == "updated"
        assert persona.read_text(encoding="utf-8").startswith("## Developer Persona")
        state = json.loads((store / "state.json").read_text(encoding="utf-8"))
        assert set(state["processed_sessions"]) == {"s1", "s2"}

    def test_failed_synthesis_marks_nothing_processed(self, tmp_path, monkeypatch):
        store = tmp_path / "store"
        persona = tmp_path / "persona.md"
        _patch_collection(monkeypatch, _fake_transcripts(tmp_path, ["s1"]))
        monkeypatch.setattr(harness, "_call_claude_cli", lambda prompt: None)
        monkeypatch.setattr(harness, "_call_anthropic_api", lambda prompt, model: None)

        status, _ = harness.run(store=store, persona_path=persona)

        assert status == "error"
        assert not persona.exists()
        assert not (store / "state.json").exists()

    def test_no_new_sessions_with_existing_persona(self, tmp_path, monkeypatch):
        store = tmp_path / "store"
        persona = tmp_path / "persona.md"
        persona.write_text("## Developer Persona\nexisting", encoding="utf-8")
        _patch_collection(monkeypatch, [])

        status, _ = harness.run(store=store, persona_path=persona)

        assert status == "nothing"

    def test_existing_persona_fed_back_into_prompt(self, tmp_path, monkeypatch):
        store = tmp_path / "store"
        persona = tmp_path / "persona.md"
        persona.write_text(
            "## Developer Persona\n### Layer 1 — Stable Identity\n"
            "### Layer 2 — Technical Knowledge Map\nPREVIOUS-CONTENT",
            encoding="utf-8",
        )
        _patch_collection(monkeypatch, _fake_transcripts(tmp_path, ["s1"]))

        seen = {}

        def fake_cli(prompt):
            seen["prompt"] = prompt
            return "## Developer Persona\nnew"

        monkeypatch.setattr(harness, "_call_claude_cli", fake_cli)

        status, _ = harness.run(store=store, persona_path=persona)

        assert status == "updated"
        assert "PREVIOUS-CONTENT" in seen["prompt"]
        assert "<developer_data>" in seen["prompt"]

    def test_malformed_existing_persona_not_fed_back(self, tmp_path, monkeypatch):
        store = tmp_path / "store"
        persona = tmp_path / "persona.md"
        persona.write_text("I refuse to synthesize a persona from this data.", encoding="utf-8")
        _patch_collection(monkeypatch, _fake_transcripts(tmp_path, ["s1"]))

        seen = {}

        def fake_cli(prompt):
            seen["prompt"] = prompt
            return "## Developer Persona\nnew"

        monkeypatch.setattr(harness, "_call_claude_cli", fake_cli)

        status, _ = harness.run(store=store, persona_path=persona)

        assert status == "updated"
        assert "EXISTING PERSONA" not in seen["prompt"]
        assert "I refuse to synthesize" not in seen["prompt"]

    def test_cli_unavailable_falls_back_to_api(self, tmp_path, monkeypatch):
        store = tmp_path / "store"
        persona = tmp_path / "persona.md"
        _patch_collection(monkeypatch, _fake_transcripts(tmp_path, ["s1"]))
        monkeypatch.setattr(harness, "_call_claude_cli", lambda prompt: None)
        monkeypatch.setattr(
            harness, "_call_anthropic_api", lambda prompt, model: "## Developer Persona\napi"
        )

        status, _ = harness.run(store=store, persona_path=persona)

        assert status == "updated"
        assert "api" in persona.read_text(encoding="utf-8")


class TestCallClaudeCli:
    def test_returns_none_when_claude_missing(self, monkeypatch):
        monkeypatch.setattr(harness.shutil, "which", lambda name: None)
        assert harness._call_claude_cli("prompt") is None
