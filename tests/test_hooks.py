from __future__ import annotations

import io
import json
import os

from agent_persona import collectors, harness
from agent_persona.hooks import stop


def _cleanup_skip_env():
    os.environ.pop("AGENT_PERSONA_SKIP", None)


def test_skip_env_short_circuits(monkeypatch):
    monkeypatch.setenv("AGENT_PERSONA_SKIP", "1")
    called = []
    monkeypatch.setattr(harness, "run", lambda **kw: called.append(kw))
    stop.main()
    assert called == []


def test_runs_harness_excluding_current_session(monkeypatch, tmp_path):
    _cleanup_skip_env()
    try:
        payload = json.dumps({"session_id": "current-session"})
        monkeypatch.setattr(stop.sys, "stdin", io.StringIO(payload))
        monkeypatch.setattr(
            collectors, "find_unprocessed_transcripts", lambda **kw: [tmp_path / "s.jsonl"]
        )
        seen = {}

        def fake_run(**kwargs):
            seen.update(kwargs)
            return ("updated", "persona.md")

        monkeypatch.setattr(harness, "run", fake_run)

        stop.main()

        assert seen["exclude_session_id"] == "current-session"
    finally:
        _cleanup_skip_env()


def test_no_transcripts_means_no_synthesis(monkeypatch):
    _cleanup_skip_env()
    try:
        monkeypatch.setattr(stop.sys, "stdin", io.StringIO("not json"))
        monkeypatch.setattr(collectors, "find_unprocessed_transcripts", lambda **kw: [])
        called = []
        monkeypatch.setattr(harness, "run", lambda **kw: called.append(kw))

        stop.main()

        assert called == []
    finally:
        _cleanup_skip_env()


def test_errors_never_propagate(monkeypatch, capsys):
    _cleanup_skip_env()
    try:
        monkeypatch.setattr(stop.sys, "stdin", io.StringIO("{}"))

        def boom(**kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(collectors, "find_unprocessed_transcripts", boom)

        stop.main()  # must not raise

        assert "boom" in capsys.readouterr().err
    finally:
        _cleanup_skip_env()
