from __future__ import annotations

import json
import os
import time
from pathlib import Path

from agent_persona import collectors


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")


def _user_msg(text: str) -> dict:
    return {"message": {"role": "user", "content": text}}


class TestRedaction:
    def test_redacts_key_value_secrets(self):
        assert "hunter2" not in collectors._redact_secrets("export API_KEY=hunter2")

    def test_redacts_flag_secrets_preserving_flag(self):
        out = collectors._redact_secrets("curl --token abc123 https://x.test")
        assert "--token [REDACTED]" in out

    def test_redacts_bare_tokens(self):
        out = collectors._redact_secrets("sk-" + "a" * 24 + " and AKIA" + "B" * 16)
        assert "sk-" not in out and "AKIA" not in out

    def test_leaves_normal_text_alone(self):
        assert collectors._redact_secrets("git commit -m fix") == "git commit -m fix"


class TestCollectTranscript:
    def test_extracts_user_messages_and_tool_signals(self, tmp_path):
        transcript = tmp_path / "s1.jsonl"
        _write_jsonl(
            transcript,
            [
                _user_msg("please fix the bug"),
                {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "name": "Read", "input": {"file_path": "/a.py"}},
                            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                        ],
                    }
                },
            ],
        )
        messages, signals = collectors.collect_transcript(transcript)
        assert messages == ["please fix the bug"]
        assert signals == ["Read: /a.py", "Bash: ls"]

    def test_skips_noise_and_meta_messages(self, tmp_path):
        transcript = tmp_path / "s2.jsonl"
        _write_jsonl(
            transcript,
            [
                _user_msg("<system-reminder>noise</system-reminder>"),
                {"isMeta": True, "message": {"role": "user", "content": "meta"}},
                _user_msg("real message"),
            ],
        )
        messages, _ = collectors.collect_transcript(transcript)
        assert messages == ["real message"]

    def test_redacts_secrets_in_messages_and_bash(self, tmp_path):
        transcript = tmp_path / "s3.jsonl"
        _write_jsonl(
            transcript,
            [
                _user_msg("my key is api_key=supersecret"),
                {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "curl --password topsecret"},
                            }
                        ],
                    }
                },
            ],
        )
        messages, signals = collectors.collect_transcript(transcript)
        assert "supersecret" not in messages[0]
        assert "topsecret" not in signals[0]

    def test_tolerates_garbage_lines(self, tmp_path):
        transcript = tmp_path / "s4.jsonl"
        transcript.write_text('not json\n[1,2]\n{"message": null}\n', encoding="utf-8")
        assert collectors.collect_transcript(transcript) == ([], [])


class TestFindUnprocessedTranscripts:
    def _make_transcript(self, claude_dir: Path, name: str, age_seconds: float = 3600) -> Path:
        path = claude_dir / "projects" / "p" / f"{name}.jsonl"
        _write_jsonl(path, [_user_msg("hi")])
        old = time.time() - age_seconds
        os.utime(path, (old, old))
        return path

    def test_finds_settled_transcripts(self, tmp_path):
        claude = tmp_path / "claude"
        self._make_transcript(claude, "aaa")
        found = collectors.find_unprocessed_transcripts(claude, tmp_path / "store")
        assert [p.stem for p in found] == ["aaa"]

    def test_skips_recent_processed_excluded_and_subagents(self, tmp_path):
        claude = tmp_path / "claude"
        store = tmp_path / "store"
        self._make_transcript(claude, "recent", age_seconds=0)
        self._make_transcript(claude, "done")
        self._make_transcript(claude, "current")
        sub = claude / "projects" / "p" / "subagents" / "sub.jsonl"
        _write_jsonl(sub, [_user_msg("hi")])
        os.utime(sub, (time.time() - 3600,) * 2)
        collectors.mark_processed("done", store)

        found = collectors.find_unprocessed_transcripts(
            claude, store, exclude_session_id="current"
        )
        assert [p.stem for p in found] == []

    def test_missing_projects_dir(self, tmp_path):
        assert collectors.find_unprocessed_transcripts(tmp_path, tmp_path / "s") == []


class TestState:
    def test_mark_processed_is_idempotent_and_capped(self, tmp_path):
        store = tmp_path / "store"
        collectors.mark_processed("x", store)
        collectors.mark_processed("x", store)
        for i in range(collectors.MAX_PROCESSED_SESSIONS + 5):
            collectors.mark_processed(f"s{i}", store)
        state = collectors._load_state(store)
        processed = state["processed_sessions"]
        assert len(processed) == collectors.MAX_PROCESSED_SESSIONS
        assert processed.count("x") == 0  # evicted by cap
        assert "last_run" in state

    def test_load_state_survives_corrupt_file(self, tmp_path):
        store = tmp_path / "store"
        store.mkdir()
        (store / "state.json").write_text("{broken", encoding="utf-8")
        assert collectors._load_state(store) == {"processed_sessions": []}


class TestShellHistory:
    def test_reads_and_redacts_zsh_history(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        (tmp_path / ".zsh_history").write_text(
            ": 1700000000:0;ls -la\n: 1700000001:0;export TOKEN=abc123\n",
            encoding="utf-8",
        )
        commands = collectors.collect_shell_history()
        assert commands[0] == "ls -la"
        assert "abc123" not in commands[1]

    def test_no_history_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        assert collectors.collect_shell_history() == []
