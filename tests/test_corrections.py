from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agent_persona.analyzers.correction_extractor import extract_corrections
from agent_persona.collectors.corrections import (
    append_corrections,
    classify_correction,
    collect_correction_events,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def _user(text: str, meta: bool = False) -> dict:
    rec = {"message": {"role": "user", "content": text}}
    if meta:
        rec["isMeta"] = True
    return rec


def _assistant_text(text: str) -> dict:
    return {"message": {"role": "assistant", "content": text}}


def _assistant_edit(path: str = "/x.py") -> dict:
    block = {"type": "tool_use", "name": "Edit", "input": {"file_path": path}}
    return {"message": {"role": "assistant", "content": [block]}}


class TestClassify:
    def test_revert(self):
        assert classify_correction("can you revert that change") == "revert"

    def test_simplify(self):
        assert classify_correction("this is way too complex, simplify it") == "simplify"

    def test_wrong_approach(self):
        assert classify_correction("that's not what i asked for") == "wrong_approach"

    def test_scope(self):
        assert classify_correction("don't add the caching yet") == "scope"

    def test_redo(self):
        assert classify_correction("no, not like that") == "redo"

    def test_bare_no_is_not_a_correction(self):
        # high-precision: casual "no" must not register
        assert classify_correction("no problem, thanks") is None
        assert classify_correction("no, that's fine") is None

    def test_neutral_text(self):
        assert classify_correction("please add a new endpoint") is None


class TestCollectEvents:
    def test_correction_after_assistant_action(self, tmp_path):
        t = tmp_path / "s.jsonl"
        _write_jsonl(t, [
            _user("fix this bug"),
            _assistant_edit(),
            _user("no, revert that, too complex"),
        ])
        events = collect_correction_events(t)
        kinds = [k for k, _ in events]
        assert "revert" in kinds or "simplify" in kinds
        # the correction reacted to an edit
        assert events[0][1] == "edit"

    def test_no_correction_before_any_assistant_turn(self, tmp_path):
        t = tmp_path / "s.jsonl"
        _write_jsonl(t, [_user("revert that")])  # nothing to correct yet
        assert collect_correction_events(t) == []

    def test_after_answer_when_no_tool(self, tmp_path):
        t = tmp_path / "s.jsonl"
        _write_jsonl(t, [
            _user("explain this"),
            _assistant_text("here is an explanation"),
            _user("that's wrong"),
        ])
        events = collect_correction_events(t)
        assert events and events[0] == ("wrong_approach", "answer")

    def test_skips_meta_and_injected(self, tmp_path):
        t = tmp_path / "s.jsonl"
        _write_jsonl(t, [
            _assistant_edit(),
            _user("revert that", meta=True),                 # meta → skip
            _user("<command-name>/x</command-name> undo"),    # injected → skip
        ])
        assert collect_correction_events(t) == []

    def test_neutral_conversation_no_events(self, tmp_path):
        t = tmp_path / "s.jsonl"
        _write_jsonl(t, [
            _user("add a feature"),
            _assistant_edit(),
            _user("great, thanks"),
        ])
        assert collect_correction_events(t) == []


def _seed(tmp_path, rows):
    """rows: list of (session_id, project, events)."""
    for sid, proj, events in rows:
        append_corrections(events, sid, proj, _now(), tmp_path)


class TestExtract:
    def test_no_file_empty(self, tmp_path):
        assert extract_corrections(tmp_path, _now()) == ()

    def test_below_session_threshold(self, tmp_path):
        _seed(tmp_path, [
            ("s1", "p1", [("simplify", "edit")]),
            ("s2", "p2", [("simplify", "edit")]),
        ])
        assert extract_corrections(tmp_path, _now()) == ()

    def test_promotes_recurring_kind(self, tmp_path):
        _seed(tmp_path, [
            ("s1", "p1", [("simplify", "edit")]),
            ("s2", "p2", [("simplify", "answer")]),
            ("s3", "p3", [("simplify", "edit")]),
        ])
        signals = extract_corrections(tmp_path, _now())
        assert len(signals) == 1
        assert signals[0].kind == "simplify"
        assert signals[0].count == 3
        assert signals[0].confidence <= 0.85

    def test_single_project_not_promoted(self, tmp_path):
        _seed(tmp_path, [
            ("s1", "samerepo", [("revert", "edit")]),
            ("s2", "samerepo", [("revert", "edit")]),
            ("s3", "samerepo", [("revert", "edit")]),
        ])
        assert extract_corrections(tmp_path, _now()) == ()

    def test_sorted_by_confidence(self, tmp_path):
        _seed(tmp_path, [
            ("s1", "p1", [("simplify", "edit"), ("scope", "edit")]),
            ("s2", "p2", [("simplify", "edit"), ("scope", "edit")]),
            ("s3", "p3", [("simplify", "edit"), ("scope", "edit")]),
            ("s4", "p4", [("simplify", "edit")]),
            ("s5", "p5", [("simplify", "edit")]),
        ])
        signals = extract_corrections(tmp_path, _now())
        confs = [s.confidence for s in signals]
        assert confs == sorted(confs, reverse=True)


class TestCompilerRenders:
    def test_renders_corrections(self):
        from agent_persona.compiler import compile_profile
        from agent_persona.models import CodingStyle, CorrectionSignal, Profile

        profile = Profile(
            version=1, languages={}, frameworks={}, tools={},
            preferences=(), coding_style=CodingStyle(),
            last_updated=_now(), sessions_processed=5, machine_fingerprint="t",
            corrections=(CorrectionSignal("simplify", 4, 0.8, _now()),),
        )
        out = compile_profile(profile)
        assert "What I often correct" in out
        assert "simplest solution" in out
