from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent_persona.models import (
    CodingStyle,
    CorrectionSignal,
    Preference,
    Profile,
    RequestPattern,
)
from agent_persona.rules import apply_rules


def _iso(dt: datetime) -> str:
    return dt.isoformat()


NOW = datetime(2026, 6, 27, tzinfo=timezone.utc)
NOW_ISO = _iso(NOW)


def _profile(**kw) -> Profile:
    base = dict(
        version=1, languages={}, frameworks={}, tools={},
        preferences=(), coding_style=CodingStyle(),
        last_updated=NOW_ISO, sessions_processed=5, machine_fingerprint="t",
        request_patterns=(), corrections=(),
    )
    base.update(kw)
    return Profile(**base)


def _pref(text, source, conf, age_days=0):
    seen = _iso(NOW - timedelta(days=age_days))
    return Preference(text=text, confidence=conf, source=source, last_seen=seen)


class TestDecay:
    def test_fresh_signal_barely_decays(self):
        p = _profile(preferences=(_pref("fresh", "llm", 0.8, age_days=0),))
        out = apply_rules(p, NOW_ISO)
        assert out.preferences[0].confidence == 0.8

    def test_old_signal_decays(self):
        p = _profile(preferences=(_pref("stale", "llm", 0.8, age_days=60),))
        out = apply_rules(p, NOW_ISO)
        # 0.8 * 0.9^(60/30) = 0.8 * 0.81 = 0.648
        assert out.preferences[0].confidence == 0.65

    def test_very_old_dropped_below_floor(self):
        # 0.5 * 0.9^(365/30) ≈ 0.5 * 0.29 ≈ 0.14 < 0.3 floor
        p = _profile(preferences=(_pref("ancient", "llm", 0.5, age_days=365),))
        out = apply_rules(p, NOW_ISO)
        assert out.preferences == ()


class TestManualExempt:
    def test_manual_never_decays_or_drops(self):
        p = _profile(preferences=(_pref("my rule", "manual", 1.0, age_days=999),))
        out = apply_rules(p, NOW_ISO)
        assert len(out.preferences) == 1
        assert out.preferences[0].confidence == 1.0
        assert out.preferences[0].source == "manual"

    def test_manual_kept_alongside_learned(self):
        p = _profile(preferences=(
            _pref("manual one", "manual", 1.0, age_days=10),
            _pref("learned one", "llm", 0.7, age_days=5),
        ))
        out = apply_rules(p, NOW_ISO)
        sources = {pr.source for pr in out.preferences}
        assert sources == {"manual", "llm"}


class TestCaps:
    def test_preferences_capped(self):
        prefs = tuple(_pref(f"p{i}", "llm", 0.9 - i * 0.01, age_days=0) for i in range(15))
        out = apply_rules(_profile(preferences=prefs), NOW_ISO)
        learned = [p for p in out.preferences if p.source == "llm"]
        assert len(learned) <= 8

    def test_corrections_capped_and_sorted(self):
        cs = tuple(
            CorrectionSignal(k, 4, c, _iso(NOW))
            for k, c in [("a", 0.5), ("b", 0.85), ("c", 0.7), ("d", 0.6), ("e", 0.55), ("f", 0.4)]
        )
        out = apply_rules(_profile(corrections=cs), NOW_ISO)
        assert len(out.corrections) <= 5
        confs = [c.confidence for c in out.corrections]
        assert confs == sorted(confs, reverse=True)


class TestRequestPatterns:
    def test_decayed_and_floored(self):
        rp_fresh = RequestPattern("bug_fix", ("causal_why",), 0.9, 5, _iso(NOW))
        rp_old = RequestPattern("refactor", ("add_test",), 0.4, 3, _iso(NOW - timedelta(days=400)))
        out = apply_rules(_profile(request_patterns=(rp_fresh, rp_old)), NOW_ISO)
        kinds = {r.trigger for r in out.request_patterns}
        assert "bug_fix" in kinds
        assert "refactor" not in kinds  # decayed below floor


class TestNonMutation:
    def test_input_profile_unchanged(self):
        prefs = (_pref("x", "llm", 0.8, age_days=60),)
        p = _profile(preferences=prefs)
        apply_rules(p, NOW_ISO)
        # original confidence untouched (decay is view-only)
        assert p.preferences[0].confidence == 0.8


class TestMute:
    def test_muted_correction_filtered(self):
        c = CorrectionSignal(kind="simplify", count=4, confidence=0.85, last_seen=NOW_ISO)
        out = apply_rules(_profile(corrections=(c,), muted=("correction:simplify",)), NOW_ISO)
        assert out.corrections == ()

    def test_unmuted_correction_kept(self):
        c = CorrectionSignal(kind="simplify", count=4, confidence=0.85, last_seen=NOW_ISO)
        out = apply_rules(_profile(corrections=(c,)), NOW_ISO)
        assert len(out.corrections) == 1

    def test_muted_stack_entry_filtered(self):
        out = apply_rules(_profile(languages={"python": 10, "go": 5}, muted=("lang:go",)), NOW_ISO)
        assert "go" not in out.languages
        assert "python" in out.languages

    def test_muted_manual_pref_filtered(self):
        p = _profile(preferences=(_pref("be concise", "manual", 1.0),), muted=("pref:be concise",))
        assert apply_rules(p, NOW_ISO).preferences == ()
