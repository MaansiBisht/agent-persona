from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


# ── session_start_hook ────────────────────────────────────────────────────────


def test_session_start_hook_compiles_persona_live(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """main() compiles the persona live from profile.json (no pre-baked context.md)."""
    import dataclasses

    from agent_persona.models import Profile
    from agent_persona.profile import save_profile

    store = tmp_path / "store"
    store.mkdir()
    profile = dataclasses.replace(
        Profile.empty("2026-01-01T00:00:00+00:00"), languages={"python": 10}
    )
    save_profile(profile, store)

    import agent_persona.hooks.session_start_hook as hook_mod

    env = {k: v for k, v in os.environ.items() if k != "AGENT_PERSONA_SKIP"}
    with patch.dict(os.environ, env, clear=True):
        with patch("agent_persona.profile.default_store", return_value=store):
            hook_mod.main()

    assert "python" in capsys.readouterr().out


def test_session_start_hook_skips_when_env_set(capsys: pytest.CaptureFixture) -> None:
    """main() returns immediately when AGENT_PERSONA_SKIP is set."""
    import agent_persona.hooks.session_start_hook as hook_mod

    with patch.dict(os.environ, {"AGENT_PERSONA_SKIP": "1"}):
        hook_mod.main()

    captured = capsys.readouterr()
    assert captured.out == ""


def test_session_start_hook_silent_when_no_persona(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """main() outputs nothing when the profile has no injectable data."""
    store = tmp_path / "store"
    store.mkdir()

    import agent_persona.hooks.session_start_hook as hook_mod

    env = {k: v for k, v in os.environ.items() if k != "AGENT_PERSONA_SKIP"}
    with patch.dict(os.environ, env, clear=True):
        with patch("agent_persona.profile.default_store", return_value=store):
            hook_mod.main()

    assert capsys.readouterr().out == ""


# ── file_hook ─────────────────────────────────────────────────────────────────


def test_file_hook_is_blocked_rejects_sensitive_paths() -> None:
    """_is_blocked() returns True for paths containing sensitive substrings."""
    from agent_persona.hooks.file_hook import _is_blocked

    assert _is_blocked("/home/user/password.txt") is True
    assert _is_blocked("/home/user/secret_key") is True
    assert _is_blocked("/project/.env") is True
    assert _is_blocked("/home/user/.key") is True
    assert _is_blocked("/path/to/credentials") is True


def test_file_hook_is_blocked_allows_normal_path() -> None:
    """_is_blocked() returns False for normal source file paths."""
    from agent_persona.hooks.file_hook import _is_blocked

    assert _is_blocked("/project/src/main.py") is False
    assert _is_blocked("/project/tests/test_app.py") is False
    assert _is_blocked("/project/app.ts") is False


def test_file_hook_compact_trims_old_lines(tmp_path: Path) -> None:
    """_compact() removes entries older than retention threshold when over limit."""
    from datetime import timedelta

    from agent_persona.hooks.file_hook import _MAX_LINES, _RETENTION_DAYS, _compact

    jsonl_path = tmp_path / "files_edited.jsonl"

    old_ts = (datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS + 10)).isoformat()
    recent_ts = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    lines = []
    for i in range(_MAX_LINES + 10):
        ts = old_ts if i < 5 else recent_ts
        lines.append(json.dumps({"path": f"/f{i}.py", "ext": ".py", "timestamp": ts}))

    jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    _compact(jsonl_path)

    remaining = [ln for ln in jsonl_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(remaining) < _MAX_LINES + 10


def test_file_hook_compact_noop_when_under_limit(tmp_path: Path) -> None:
    """_compact() leaves a small file untouched."""
    from agent_persona.hooks.file_hook import _compact

    jsonl_path = tmp_path / "files_edited.jsonl"
    recent_ts = datetime.now(timezone.utc).isoformat()
    lines = [json.dumps({"path": "/f.py", "ext": ".py", "timestamp": recent_ts})]
    original_content = "\n".join(lines) + "\n"
    jsonl_path.write_text(original_content, encoding="utf-8")

    _compact(jsonl_path)

    assert jsonl_path.read_text(encoding="utf-8") == original_content


def test_file_hook_main_writes_record_from_argv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """main() writes a JSONL record for a valid file_path from argv."""
    import agent_persona.hooks.file_hook as hook_mod

    store = tmp_path / "store"
    monkeypatch.setattr("agent_persona.profile.default_store", lambda: store)

    with patch.object(sys, "argv", ["file_hook", "/project/src/app.py"]):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = ""
            hook_mod.main()

    log_path = store / "history" / "files_edited.jsonl"
    assert log_path.exists()
    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert record["ext"] == ".py"
    assert record["path"].endswith("app.py")


def test_file_hook_main_writes_record_from_stdin_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """main() reads file_path from JSON on stdin when available."""
    import agent_persona.hooks.file_hook as hook_mod

    store = tmp_path / "store"
    monkeypatch.setattr("agent_persona.profile.default_store", lambda: store)

    stdin_data = json.dumps({"tool_input": {"file_path": "/project/src/utils.ts"}})
    with patch.object(sys, "argv", ["file_hook"]):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = stdin_data
            hook_mod.main()

    log_path = store / "history" / "files_edited.jsonl"
    assert log_path.exists()
    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert record["ext"] == ".ts"


def test_file_hook_main_skips_blocked_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """main() does not write a record when the file_path is blocked."""
    import agent_persona.hooks.file_hook as hook_mod

    store = tmp_path / "store"
    monkeypatch.setattr("agent_persona.profile.default_store", lambda: store)

    with patch.object(sys, "argv", ["file_hook", "/home/user/.env"]):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = ""
            hook_mod.main()

    log_path = store / "history" / "files_edited.jsonl"
    assert not log_path.exists()


def test_file_hook_main_no_path_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """main() does nothing when no file path is provided."""
    import agent_persona.hooks.file_hook as hook_mod

    store = tmp_path / "store"
    monkeypatch.setattr("agent_persona.profile.default_store", lambda: store)

    with patch.object(sys, "argv", ["file_hook"]):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = ""
            hook_mod.main()

    log_path = store / "history" / "files_edited.jsonl"
    assert not log_path.exists()


def test_file_hook_main_stdin_bad_json_falls_back_to_argv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """main() falls back to argv when stdin is not valid JSON."""
    import agent_persona.hooks.file_hook as hook_mod

    store = tmp_path / "store"
    monkeypatch.setattr("agent_persona.profile.default_store", lambda: store)

    with patch.object(sys, "argv", ["file_hook", "/project/main.rs"]):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = "NOT JSON"
            hook_mod.main()

    log_path = store / "history" / "files_edited.jsonl"
    assert log_path.exists()
    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert record["ext"] == ".rs"


# ── stop_hook ─────────────────────────────────────────────────────────────────


def test_stop_hook_run_pipeline_writes_profile_not_context(tmp_path: Path) -> None:
    """run_pipeline() persists profile.json and writes no context.md (compile-on-read)."""
    from agent_persona.hooks.stop_hook import run_pipeline

    store = tmp_path / "store"
    store.mkdir()

    with patch("agent_persona.collectors.transcript.find_unprocessed_transcripts", return_value=[]):
        with patch("agent_persona.collectors.shell_history.collect_shell_history", return_value=[]):
            run_pipeline(store=store)

    assert (store / "profile.json").exists()
    assert not (store / "generated" / "context.md").exists()


def test_stop_hook_run_pipeline_processes_transcript(tmp_path: Path) -> None:
    """run_pipeline() processes a transcript and saves profile data."""
    from agent_persona.hooks.stop_hook import run_pipeline

    store = tmp_path / "store"
    store.mkdir()

    transcript = tmp_path / "session_abc.jsonl"
    record = {"message": {"role": "user", "content": "I prefer typed Python code"}}
    transcript.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with patch(
        "agent_persona.collectors.transcript.find_unprocessed_transcripts",
        return_value=[transcript],
    ):
        with patch("agent_persona.collectors.shell_history.collect_shell_history", return_value=[]):
            with patch("agent_persona.collectors.transcript.mark_processed"):
                run_pipeline(store=store)

    profile_path = store / "profile.json"
    assert profile_path.exists()


def test_stop_hook_run_pipeline_handles_bad_transcript(tmp_path: Path) -> None:
    """run_pipeline() silently skips transcripts that raise during processing."""
    from agent_persona.hooks.stop_hook import run_pipeline

    store = tmp_path / "store"
    store.mkdir()

    bad_transcript = tmp_path / "bad_session.jsonl"
    bad_transcript.write_text("INVALID JSON\n", encoding="utf-8")

    with patch(
        "agent_persona.collectors.transcript.find_unprocessed_transcripts",
        return_value=[bad_transcript],
    ):
        with patch("agent_persona.collectors.shell_history.collect_shell_history", return_value=[]):
            # Should not raise even with bad data
            run_pipeline(store=store)


def test_stop_hook_main_calls_run_pipeline() -> None:
    """main() calls run_pipeline() without raising."""
    import agent_persona.hooks.stop_hook as hook_mod

    with patch.object(hook_mod, "run_pipeline") as mock_pipeline:
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = ""
            hook_mod.main()

    mock_pipeline.assert_called_once()


def test_stop_hook_main_with_stdin_json() -> None:
    """main() reads stdin JSON without error even if it contains arbitrary data."""
    import agent_persona.hooks.stop_hook as hook_mod

    with patch.object(hook_mod, "run_pipeline"):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = json.dumps({"stop_reason": "done"})
            hook_mod.main()  # should not raise
