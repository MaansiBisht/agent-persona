from __future__ import annotations

from click.testing import CliRunner

from agent_persona import cli as cli_module
from agent_persona import installer
from agent_persona.cli import main


def _isolate(monkeypatch, tmp_path):
    """Point the CLI at tmp paths so tests never touch real ~/.claude."""
    monkeypatch.setattr(cli_module, "STORE", tmp_path / "store")
    monkeypatch.setattr(cli_module, "PERSONA", tmp_path / "persona.md")


def test_show_without_persona(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    result = CliRunner().invoke(main, ["show"])
    assert result.exit_code == 0
    assert "No persona yet" in result.output


def test_show_prints_persona(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    cli_module.PERSONA.write_text("## Developer Persona\nhello", encoding="utf-8")
    result = CliRunner().invoke(main, ["show"])
    assert "Developer Persona" in result.output


def test_run_updated_and_already_bound(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_module.harness, "run", lambda **kw: ("updated", "persona.md"))
    monkeypatch.setattr(installer, "is_bound", lambda *a: True)
    result = CliRunner().invoke(main, ["run"])
    assert result.exit_code == 0
    assert "persona.md written" in result.output
    assert "Already bound" in result.output


def test_run_offers_bind_and_declines(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_module.harness, "run", lambda **kw: ("updated", "persona.md"))
    monkeypatch.setattr(installer, "is_bound", lambda *a: False)
    result = CliRunner().invoke(main, ["run"], input="n\n")
    assert result.exit_code == 0
    assert "Bind to all future Claude Code sessions?" in result.output


def test_run_nothing(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_module.harness, "run", lambda **kw: ("nothing", "no new sessions"))
    result = CliRunner().invoke(main, ["run"])
    assert result.exit_code == 0
    assert "no new sessions" in result.output


def test_run_error_exits_nonzero(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_module.harness, "run", lambda **kw: ("error", "claude not found"))
    result = CliRunner().invoke(main, ["run"])
    assert result.exit_code == 1
    assert "claude not found" in result.output


def test_install_reports_bindings(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(installer, "install", lambda persona: {"claude_md": True, "stop_hook": True})
    result = CliRunner().invoke(main, ["install"])
    assert result.exit_code == 0
    assert "Bound." in result.output
    assert "Stop hook registered." in result.output


def test_uninstall_with_purge(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    cli_module.STORE.mkdir(parents=True)
    monkeypatch.setattr(installer, "uninstall", lambda: {"claude_md": True, "stop_hook": True})
    result = CliRunner().invoke(main, ["uninstall", "--purge"])
    assert result.exit_code == 0
    assert "Removed" in result.output
    assert not cli_module.STORE.exists()


def test_doctor_runs_all_checks(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(installer, "is_bound", lambda *a: True)
    monkeypatch.setattr(installer, "stop_hook_installed", lambda *a: True)
    monkeypatch.setattr(installer, "legacy_hooks_present", lambda *a: False)
    result = CliRunner().invoke(main, ["doctor"])
    assert result.exit_code == 0
    assert "No legacy 0.3.x hooks" in result.output


def test_doctor_flags_legacy_hooks(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(installer, "is_bound", lambda *a: True)
    monkeypatch.setattr(installer, "stop_hook_installed", lambda *a: True)
    monkeypatch.setattr(installer, "legacy_hooks_present", lambda *a: True)
    result = CliRunner().invoke(main, ["doctor"])
    assert "FAIL" in result.output and "stale" in result.output
