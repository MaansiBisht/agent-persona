from __future__ import annotations

import json
from datetime import datetime, timezone

from agent_persona.analyzers.request_pattern_extractor import extract_request_patterns
from agent_persona.collectors.request_patterns import (
    append_observation,
    classify,
    collect_transitions,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TestClassify:
    def test_bug_fix(self):
        assert classify("can you fix this broken function") == "bug_fix"

    def test_causal_why(self):
        assert classify("why did that happen") == "causal_why"

    def test_add_test(self):
        assert classify("add test coverage for this") == "add_test"

    def test_refactor(self):
        assert classify("let's refactor this module") == "refactor"

    def test_explain(self):
        assert classify("explain how this works") == "explain"

    def test_unmatched_returns_none(self):
        assert classify("hello there friend") is None

    def test_first_match_wins(self):
        # contains both "fix" and "why" — bug_fix is earlier in the vocabulary
        assert classify("fix this and tell me why") == "bug_fix"


class TestCollectTransitions:
    def test_simple_transition(self):
        msgs = ["fix this bug", "why did it happen"]
        assert collect_transitions(msgs) == [("bug_fix", "causal_why")]

    def test_skips_same_tag_repeats(self):
        msgs = ["fix this", "fix that too"]
        assert collect_transitions(msgs) == []

    def test_skips_unclassified_messages(self):
        msgs = ["fix this bug", "hmm ok thanks", "why did it happen"]
        assert collect_transitions(msgs) == [("bug_fix", "causal_why")]

    def test_dedups_within_session(self):
        msgs = ["fix this", "why", "fix that", "why again"]
        result = collect_transitions(msgs)
        assert result.count(("bug_fix", "causal_why")) == 1
        assert ("causal_why", "bug_fix") in result

    def test_empty_messages(self):
        assert collect_transitions([]) == []

    def test_bounded_to_vocabulary(self):
        msgs = ["fix", "why", "test", "refactor", "explain"] * 100
        result = collect_transitions(msgs)
        assert len(result) <= 20
        assert len(result) == len(set(result))


class TestAppendObservation:
    def test_writes_jsonl(self, tmp_path):
        append_observation([("bug_fix", "causal_why")], "sess1", "proj1", _now(), tmp_path)
        log = tmp_path / "request_patterns.jsonl"
        assert log.exists()
        record = json.loads(log.read_text().strip())
        assert record["session_id"] == "sess1"
        assert record["project"] == "proj1"
        assert record["transitions"] == [["bug_fix", "causal_why"]]

    def test_empty_transitions_writes_nothing(self, tmp_path):
        append_observation([], "sess1", "proj1", _now(), tmp_path)
        assert not (tmp_path / "request_patterns.jsonl").exists()

    def test_appends_multiple(self, tmp_path):
        append_observation([("bug_fix", "causal_why")], "s1", "p1", _now(), tmp_path)
        append_observation([("refactor", "add_test")], "s2", "p2", _now(), tmp_path)
        lines = (tmp_path / "request_patterns.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2


def _seed(tmp_path, sessions):
    """sessions: list of (session_id, project, transitions)."""
    for sid, proj, transitions in sessions:
        append_observation(transitions, sid, proj, _now(), tmp_path)


class TestExtractRequestPatterns:
    def test_no_file_returns_empty(self, tmp_path):
        assert extract_request_patterns(tmp_path, _now()) == ()

    def test_below_session_threshold_not_extracted(self, tmp_path):
        _seed(tmp_path, [
            ("s1", "p1", [("bug_fix", "causal_why")]),
            ("s2", "p2", [("bug_fix", "causal_why")]),
        ])
        assert extract_request_patterns(tmp_path, _now()) == ()

    def test_extracts_strong_pattern(self, tmp_path):
        _seed(tmp_path, [
            ("s1", "p1", [("bug_fix", "causal_why")]),
            ("s2", "p2", [("bug_fix", "causal_why")]),
            ("s3", "p3", [("bug_fix", "causal_why")]),
        ])
        patterns = extract_request_patterns(tmp_path, _now())
        assert len(patterns) == 1
        assert patterns[0].trigger == "bug_fix"
        assert patterns[0].always_include == ("causal_why",)
        assert patterns[0].seen_count == 3

    def test_below_frequency_threshold_not_extracted(self, tmp_path):
        _seed(tmp_path, [
            ("s1", "p1", [("bug_fix", "causal_why")]),
            ("s2", "p2", [("bug_fix", "causal_why")]),
            ("s3", "p3", [("bug_fix", "add_test")]),
            ("s4", "p4", [("bug_fix", "add_test")]),
            ("s5", "p5", [("bug_fix", "refactor")]),
        ])
        patterns = extract_request_patterns(tmp_path, _now())
        triggers = [(p.trigger, p.always_include) for p in patterns]
        assert ("bug_fix", ("causal_why",)) not in triggers

    def test_single_project_not_extracted(self, tmp_path):
        _seed(tmp_path, [
            ("s1", "samerepo", [("bug_fix", "causal_why")]),
            ("s2", "samerepo", [("bug_fix", "causal_why")]),
            ("s3", "samerepo", [("bug_fix", "causal_why")]),
        ])
        assert extract_request_patterns(tmp_path, _now()) == ()

    def test_confidence_capped_at_090(self, tmp_path):
        _seed(tmp_path, [
            (f"s{i}", f"p{i}", [("bug_fix", "causal_why")])
            for i in range(8)
        ])
        patterns = extract_request_patterns(tmp_path, _now())
        assert patterns[0].confidence <= 0.90

    def test_caps_at_ten_patterns(self, tmp_path):
        tags = ["bug_fix", "causal_why", "add_test", "refactor", "explain"]
        sessions = []
        idx = 0
        for a in tags:
            for b in tags:
                if a == b:
                    continue
                for s in range(3):
                    sessions.append((f"s{idx}_{s}", f"p{s}", [(a, b)]))
                idx += 1
        _seed(tmp_path, sessions)
        patterns = extract_request_patterns(tmp_path, _now())
        assert len(patterns) <= 10

    def test_sorted_by_confidence_desc(self, tmp_path):
        _seed(tmp_path, [
            ("a1", "p1", [("bug_fix", "causal_why")]),
            ("a2", "p2", [("bug_fix", "causal_why")]),
            ("a3", "p3", [("bug_fix", "causal_why")]),
            ("a4", "p4", [("bug_fix", "causal_why")]),
            ("a5", "p5", [("bug_fix", "causal_why")]),
            ("b1", "p1", [("refactor", "add_test")]),
            ("b2", "p2", [("refactor", "add_test")]),
            ("b3", "p3", [("refactor", "add_test")]),
        ])
        patterns = extract_request_patterns(tmp_path, _now())
        confidences = [p.confidence for p in patterns]
        assert confidences == sorted(confidences, reverse=True)

    def test_skips_malformed_lines(self, tmp_path):
        log = tmp_path / "request_patterns.jsonl"
        log.write_text(
            "not json\n"
            + json.dumps({"session_id": "s1", "project": "p1", "ts": _now(),
                          "transitions": [["bug_fix", "causal_why"]]}) + "\n"
            + '{"transitions": "wrong type"}\n'
        )
        result = extract_request_patterns(tmp_path, _now())
        assert isinstance(result, tuple)


class TestCompactionAndRendering:
    def test_compaction_drops_old_lines(self, tmp_path):
        from datetime import timedelta

        from agent_persona.collectors import request_patterns as rp_mod

        old_ts = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
        log = tmp_path / "request_patterns.jsonl"
        # write > _MAX_LINES old entries, then one fresh append triggers compaction
        old_lines = [
            json.dumps({"session_id": f"old{i}", "project": "p", "ts": old_ts,
                        "transitions": [["bug_fix", "causal_why"]]})
            for i in range(rp_mod._MAX_LINES + 5)
        ]
        log.write_text("\n".join(old_lines) + "\n")
        append_observation([("refactor", "add_test")], "fresh", "p", _now(), tmp_path)
        remaining = log.read_text().strip().splitlines()
        # old entries pruned; only the fresh one survives
        assert all("old" not in line for line in remaining)
        assert any("fresh" in line for line in remaining)

    def test_compiler_renders_request_patterns(self):
        from agent_persona.compiler import compile_profile
        from agent_persona.models import CodingStyle, Profile, RequestPattern

        profile = Profile(
            version=1,
            languages={},
            frameworks={},
            tools={},
            preferences=(),
            coding_style=CodingStyle(),
            last_updated=_now(),
            sessions_processed=5,
            machine_fingerprint="test",
            request_patterns=(
                RequestPattern(
                    trigger="bug_fix",
                    always_include=("causal_why",),
                    confidence=0.9,
                    seen_count=5,
                    last_seen=_now(),
                ),
            ),
        )
        output = compile_profile(profile)
        assert "How I follow up:" in output
        assert "fix a bug" in output
        assert "root cause" in output
