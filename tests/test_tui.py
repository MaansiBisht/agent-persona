from __future__ import annotations

from datetime import datetime, timezone


from agent_persona.models import CodingStyle, Preference, Profile
from agent_persona.profile import load_profile, save_profile
from agent_persona.tui import (
    _add_preference,
    _learned_signals,
    _manage_learned,
    _manual_prefs,
    _remove_preferences,
    _view_preferences,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_profile() -> Profile:
    return Profile(
        version=1,
        languages={},
        frameworks={},
        tools={},
        preferences=(),
        coding_style=CodingStyle(),
        last_updated=_now(),
        sessions_processed=0,
        machine_fingerprint="test",
    )


def _pref(text: str, source: str = "manual") -> Preference:
    return Preference(text=text, confidence=1.0, source=source, last_seen=_now())


class TestManualPrefs:
    def test_returns_only_manual(self):
        profile = Profile(
            version=1,
            languages={},
            frameworks={},
            tools={},
            preferences=(
                _pref("manual one", "manual"),
                _pref("llm one", "llm"),
                _pref("manual two", "manual"),
            ),
            coding_style=CodingStyle(),
            last_updated=_now(),
            sessions_processed=0,
            machine_fingerprint="test",
        )
        result = _manual_prefs(profile)
        assert len(result) == 2
        assert all(p.source == "manual" for p in result)

    def test_empty_returns_empty(self):
        assert _manual_prefs(_empty_profile()) == []


class TestAddPreference:
    def test_adds_new_preference(self, tmp_path):
        save_profile(_empty_profile(), tmp_path)
        _add_preference("use type hints always", tmp_path)
        profile = load_profile(tmp_path)
        manual = _manual_prefs(profile)
        assert len(manual) == 1
        assert manual[0].text == "use type hints always"
        assert manual[0].source == "manual"
        assert manual[0].confidence == 1.0

    def test_strips_whitespace(self, tmp_path):
        save_profile(_empty_profile(), tmp_path)
        _add_preference("  trailing spaces  ", tmp_path)
        profile = load_profile(tmp_path)
        assert _manual_prefs(profile)[0].text == "trailing spaces"

    def test_duplicate_not_added(self, tmp_path):
        save_profile(_empty_profile(), tmp_path)
        _add_preference("prefer short functions", tmp_path)
        _add_preference("prefer short functions", tmp_path)
        profile = load_profile(tmp_path)
        assert len(_manual_prefs(profile)) == 1

    def test_case_insensitive_dedup(self, tmp_path):
        save_profile(_empty_profile(), tmp_path)
        _add_preference("Prefer Short Functions", tmp_path)
        _add_preference("prefer short functions", tmp_path)
        profile = load_profile(tmp_path)
        assert len(_manual_prefs(profile)) == 1

    def test_does_not_remove_auto_preferences(self, tmp_path):
        base = Profile(
            version=1,
            languages={},
            frameworks={},
            tools={},
            preferences=(_pref("learned pref", "llm"),),
            coding_style=CodingStyle(),
            last_updated=_now(),
            sessions_processed=0,
            machine_fingerprint="test",
        )
        save_profile(base, tmp_path)
        _add_preference("manual pref", tmp_path)
        profile = load_profile(tmp_path)
        assert len(profile.preferences) == 2

    def test_multiple_adds_accumulate(self, tmp_path):
        save_profile(_empty_profile(), tmp_path)
        _add_preference("pref one", tmp_path)
        _add_preference("pref two", tmp_path)
        _add_preference("pref three", tmp_path)
        profile = load_profile(tmp_path)
        assert len(_manual_prefs(profile)) == 3


class TestRemovePreferences:
    def test_removes_selected(self, tmp_path, monkeypatch):
        base = Profile(
            version=1,
            languages={},
            frameworks={},
            tools={},
            preferences=(
                _pref("keep this"),
                _pref("remove this"),
            ),
            coding_style=CodingStyle(),
            last_updated=_now(),
            sessions_processed=0,
            machine_fingerprint="test",
        )
        save_profile(base, tmp_path)

        import questionary as q
        monkeypatch.setattr(
            q,
            "checkbox",
            lambda *a, **kw: type("_Q", (), {"ask": lambda self: ["remove this"]})(),
        )

        _remove_preferences(tmp_path)
        profile = load_profile(tmp_path)
        manual = _manual_prefs(profile)
        assert len(manual) == 1
        assert manual[0].text == "keep this"

    def test_no_op_on_empty_cancel(self, tmp_path, monkeypatch):
        base = Profile(
            version=1,
            languages={},
            frameworks={},
            tools={},
            preferences=(_pref("keep"),),
            coding_style=CodingStyle(),
            last_updated=_now(),
            sessions_processed=0,
            machine_fingerprint="test",
        )
        save_profile(base, tmp_path)

        import questionary as q
        monkeypatch.setattr(
            q,
            "checkbox",
            lambda *a, **kw: type("_Q", (), {"ask": lambda self: []})(),
        )

        _remove_preferences(tmp_path)
        assert len(_manual_prefs(load_profile(tmp_path))) == 1


class TestManageLearned:
    def test_learned_signals_excludes_manual_prefs(self):
        import dataclasses

        from agent_persona.models import CorrectionSignal

        profile = dataclasses.replace(
            _empty_profile(),
            languages={"python": 5},
            corrections=(CorrectionSignal(kind="simplify", count=4, confidence=0.85, last_seen=_now()),),
            preferences=(_pref("manual one", "manual"),),
        )
        ids = [sid for sid, _ in _learned_signals(profile)]
        assert "lang:python" in ids
        assert "correction:simplify" in ids
        assert "pref:manual one" not in ids

    def test_mute_saves_selection(self, tmp_path, monkeypatch):
        import dataclasses

        from agent_persona.models import CorrectionSignal

        profile = dataclasses.replace(
            _empty_profile(),
            corrections=(CorrectionSignal(kind="simplify", count=4, confidence=0.85, last_seen=_now()),),
        )
        save_profile(profile, tmp_path)

        import questionary as q
        monkeypatch.setattr(
            q,
            "checkbox",
            lambda *a, **kw: type("_Q", (), {"ask": lambda self: ["correction:simplify"]})(),
        )

        _manage_learned(tmp_path)
        assert load_profile(tmp_path).muted == ("correction:simplify",)


class TestViewPreferences:
    def test_no_crash_on_empty(self):
        _view_preferences(_empty_profile())

    def test_no_crash_with_prefs(self):
        profile = Profile(
            version=1,
            languages={},
            frameworks={},
            tools={},
            preferences=(_pref("test pref"),),
            coding_style=CodingStyle(),
            last_updated=_now(),
            sessions_processed=0,
            machine_fingerprint="test",
        )
        _view_preferences(profile)
