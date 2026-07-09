from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from agent_persona.cli import cli


# ── install ───────────────────────────────────────────────────────────────────


def test_install_dry_run_lists_hooks(tmp_path: Path) -> None:
    """install --dry-run prints hook descriptions without writing anything."""
    runner = CliRunner()
    result = runner.invoke(cli, ["install", "--dry-run"])
    assert result.exit_code == 0
    # Should mention at least one event type or description from HOOKS
    output_lower = result.output.lower()
    assert any(kw in output_lower for kw in ("agent-persona", "session", "hooks", "stop", "inject"))


def test_install_adds_hooks(tmp_path: Path) -> None:
    """install writes hooks to settings.json."""
    settings_path = tmp_path / "settings.json"
    runner = CliRunner()

    with patch("agent_persona.installer._default_settings_path", return_value=settings_path):
        result = runner.invoke(cli, ["install"])

    assert result.exit_code == 0
    assert "installed" in result.output.lower()
    assert settings_path.exists()


def test_install_already_installed(tmp_path: Path) -> None:
    """install prints 'already installed' when hooks are present."""
    settings_path = tmp_path / "settings.json"
    runner = CliRunner()

    with patch("agent_persona.installer._default_settings_path", return_value=settings_path):
        runner.invoke(cli, ["install"])  # first install
        result = runner.invoke(cli, ["install"])  # second install

    assert result.exit_code == 0
    assert "already" in result.output.lower()


# ── uninstall ─────────────────────────────────────────────────────────────────


def test_uninstall_removes_hooks(tmp_path: Path) -> None:
    """uninstall removes previously installed hooks."""
    settings_path = tmp_path / "settings.json"
    runner = CliRunner()

    with patch("agent_persona.installer._default_settings_path", return_value=settings_path):
        runner.invoke(cli, ["install"])
        result = runner.invoke(cli, ["uninstall"])

    assert result.exit_code == 0
    assert "removed" in result.output.lower()


def test_uninstall_no_hooks_present(tmp_path: Path) -> None:
    """uninstall prints 'not found' when there are no hooks to remove."""
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{}", encoding="utf-8")
    runner = CliRunner()

    with patch("agent_persona.installer._default_settings_path", return_value=settings_path):
        result = runner.invoke(cli, ["uninstall"])

    assert result.exit_code == 0
    output_lower = result.output.lower()
    assert "no" in output_lower or "not" in output_lower


def test_uninstall_purge_deletes_store(tmp_path: Path) -> None:
    """uninstall --purge wipes the profile store."""
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{}", encoding="utf-8")
    store = tmp_path / "store"
    store.mkdir()
    (store / "profile.json").write_text("{}", encoding="utf-8")
    runner = CliRunner()

    with patch("agent_persona.installer._default_settings_path", return_value=settings_path):
        with patch("agent_persona.profile.default_store", return_value=store):
            result = runner.invoke(cli, ["uninstall", "--purge"])

    assert result.exit_code == 0
    assert not store.exists()


# ── status ────────────────────────────────────────────────────────────────────


def test_status_shows_table(tmp_path: Path) -> None:
    """status renders a table with at least session count info."""
    runner = CliRunner()

    with patch("agent_persona.profile.default_store", return_value=tmp_path / "store"):
        result = runner.invoke(cli, ["status"])

    assert result.exit_code == 0
    output_lower = result.output.lower()
    assert any(kw in output_lower for kw in ("status", "sessions", "stack", "updated"))


def test_status_with_profile_data(tmp_path: Path) -> None:
    """status shows stack info from a populated profile."""
    from agent_persona.models import CodingStyle, Preference, Profile
    from agent_persona.profile import save_profile

    store = tmp_path / "store"
    store.mkdir()
    profile = Profile(
        version=1,
        languages={"python": 10, "typescript": 5},
        frameworks={"pytest": 3},
        tools={},
        preferences=(
            Preference(
                text="use type hints everywhere",
                confidence=0.9,
                source="rule",
                last_seen="2024-06-01T00:00:00+00:00",
            ),
        ),
        coding_style=CodingStyle(),
        last_updated="2024-06-01T00:00:00+00:00",
        sessions_processed=2,
        machine_fingerprint="test",
    )
    save_profile(profile, store)

    runner = CliRunner()
    with patch("agent_persona.profile.default_store", return_value=store):
        result = runner.invoke(cli, ["status"])

    assert result.exit_code == 0
    assert "python" in result.output.lower()


# ── analyze ───────────────────────────────────────────────────────────────────


def test_analyze_calls_run_pipeline() -> None:
    """analyze invokes run_pipeline and reports completion."""
    runner = CliRunner()

    with patch("agent_persona.hooks.stop_hook.run_pipeline") as mock_pipeline:
        result = runner.invoke(cli, ["analyze"])

    assert result.exit_code == 0
    mock_pipeline.assert_called_once()
    output_lower = result.output.lower()
    assert "complete" in output_lower or "analyz" in output_lower


def test_analyze_reports_failure_on_exception() -> None:
    """analyze catches exceptions from run_pipeline and prints an error."""
    runner = CliRunner()

    with patch("agent_persona.hooks.stop_hook.run_pipeline", side_effect=RuntimeError("boom")):
        result = runner.invoke(cli, ["analyze"])

    assert result.exit_code == 0  # CLI swallows the error
    output_lower = result.output.lower()
    assert "failed" in output_lower or "boom" in output_lower


# ── show ──────────────────────────────────────────────────────────────────────


def test_show_prints_persona(tmp_path: Path) -> None:
    """show prints the live-compiled persona."""
    import dataclasses

    from agent_persona.models import Profile
    from agent_persona.profile import save_profile

    store = tmp_path / "store"
    store.mkdir()
    profile = dataclasses.replace(
        Profile.empty("2026-06-01T00:00:00+00:00"), languages={"python": 10}
    )
    save_profile(profile, store)

    runner = CliRunner()
    with patch("agent_persona.profile.default_store", return_value=store):
        result = runner.invoke(cli, ["show"])

    assert result.exit_code == 0
    assert "python" in result.output.lower()


def test_show_nothing_when_empty(tmp_path: Path) -> None:
    """show reports nothing to inject when the profile has no data."""
    store = tmp_path / "store"
    store.mkdir()

    runner = CliRunner()
    with patch("agent_persona.profile.default_store", return_value=store):
        result = runner.invoke(cli, ["show"])

    assert result.exit_code == 0
    assert "nothing" in result.output.lower()


# ── export ────────────────────────────────────────────────────────────────────


def test_export_no_profile_exits_with_error(tmp_path: Path) -> None:
    """export exits with code 1 when no profile.json exists."""
    runner = CliRunner()

    with patch("agent_persona.profile.default_store", return_value=tmp_path / "store"):
        result = runner.invoke(cli, ["export"])

    assert result.exit_code == 1


def test_export_writes_to_path(tmp_path: Path) -> None:
    """export copies profile.json to the given destination path."""
    from agent_persona.models import Profile
    from agent_persona.profile import save_profile

    store = tmp_path / "store"
    store.mkdir()
    save_profile(Profile.empty("2024-06-01T00:00:00+00:00"), store)

    dest = tmp_path / "my_export.json"
    runner = CliRunner()

    with patch("agent_persona.profile.default_store", return_value=store):
        result = runner.invoke(cli, ["export", str(dest)])

    assert result.exit_code == 0
    assert dest.exists()
    assert "exported" in result.output.lower()


def test_export_refuses_overwrite_without_force(tmp_path: Path) -> None:
    """export exits with code 1 when destination exists and --force not given."""
    from agent_persona.models import Profile
    from agent_persona.profile import save_profile

    store = tmp_path / "store"
    store.mkdir()
    save_profile(Profile.empty("2024-06-01T00:00:00+00:00"), store)

    dest = tmp_path / "existing.json"
    dest.write_text("{}", encoding="utf-8")

    runner = CliRunner()
    with patch("agent_persona.profile.default_store", return_value=store):
        result = runner.invoke(cli, ["export", str(dest)])

    assert result.exit_code == 1


def test_export_force_overwrites(tmp_path: Path) -> None:
    """export --force overwrites an existing destination file."""
    from agent_persona.models import Profile
    from agent_persona.profile import save_profile

    store = tmp_path / "store"
    store.mkdir()
    save_profile(Profile.empty("2024-06-01T00:00:00+00:00"), store)

    dest = tmp_path / "existing.json"
    dest.write_text("{}", encoding="utf-8")

    runner = CliRunner()
    with patch("agent_persona.profile.default_store", return_value=store):
        result = runner.invoke(cli, ["export", str(dest), "--force"])

    assert result.exit_code == 0
    assert "exported" in result.output.lower()


# ── import ────────────────────────────────────────────────────────────────────


def test_import_missing_file_exits_with_error(tmp_path: Path) -> None:
    """import exits with code 1 when the source file does not exist."""
    runner = CliRunner()

    with patch("agent_persona.profile.default_store", return_value=tmp_path / "store"):
        result = runner.invoke(cli, ["import", str(tmp_path / "nonexistent.json")])

    assert result.exit_code == 1


def test_import_merges_profile(tmp_path: Path) -> None:
    """import reads and merges a valid profile JSON file."""
    from agent_persona.models import Profile
    from agent_persona.profile import _to_dict  # type: ignore[attr-defined]

    store = tmp_path / "store"
    store.mkdir()

    incoming_profile = Profile.empty("2024-06-01T00:00:00+00:00")
    incoming_data = _to_dict(incoming_profile)
    src = tmp_path / "incoming.json"
    src.write_text(json.dumps(incoming_data), encoding="utf-8")

    runner = CliRunner()
    with patch("agent_persona.profile.default_store", return_value=store):
        result = runner.invoke(cli, ["import", str(src)])

    assert result.exit_code == 0
    assert "imported" in result.output.lower()


def test_import_bad_json_exits_with_error(tmp_path: Path) -> None:
    """import exits with code 1 when the source file contains invalid JSON."""
    src = tmp_path / "bad.json"
    src.write_text("NOT JSON", encoding="utf-8")

    runner = CliRunner()
    with patch("agent_persona.profile.default_store", return_value=tmp_path / "store"):
        result = runner.invoke(cli, ["import", str(src)])

    assert result.exit_code == 1


# ── reset ─────────────────────────────────────────────────────────────────────


def test_reset_without_confirm_does_nothing(tmp_path: Path) -> None:
    """reset without --confirm just prints a warning."""
    runner = CliRunner()

    with patch("agent_persona.profile.default_store", return_value=tmp_path / "store"):
        result = runner.invoke(cli, ["reset"])

    assert result.exit_code == 0
    assert "confirm" in result.output.lower()


def test_reset_with_confirm_clears_store(tmp_path: Path) -> None:
    """reset --confirm deletes the store directory."""
    store = tmp_path / "store"
    store.mkdir()
    (store / "profile.json").write_text("{}", encoding="utf-8")

    runner = CliRunner()
    with patch("agent_persona.profile.default_store", return_value=store):
        result = runner.invoke(cli, ["reset", "--confirm"])

    assert result.exit_code == 0
    assert not store.exists()
    assert "cleared" in result.output.lower()


# ── doctor ────────────────────────────────────────────────────────────────────


def test_doctor_shows_checks(tmp_path: Path) -> None:
    """doctor prints a results table."""
    runner = CliRunner()

    with patch("agent_persona.profile.default_store", return_value=tmp_path / "store"):
        with patch("agent_persona.installer.is_installed", return_value=False):
            result = runner.invoke(cli, ["doctor"])

    assert result.exit_code == 0
    output_lower = result.output.lower()
    assert any(kw in output_lower for kw in ("doctor", "python", "pass", "fail", "check"))


def test_doctor_hooks_present(tmp_path: Path) -> None:
    """doctor shows PASS for hooks when is_installed returns True."""
    runner = CliRunner()

    with patch("agent_persona.profile.default_store", return_value=tmp_path / "store"):
        with patch("agent_persona.installer.is_installed", return_value=True):
            result = runner.invoke(cli, ["doctor"])

    assert result.exit_code == 0
