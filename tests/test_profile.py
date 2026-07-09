from __future__ import annotations

import json
from pathlib import Path


from agent_persona.models import CodingStyle, Preference, Profile
from agent_persona.profile import _to_dict, load_profile, merge_profile, save_profile

NOW = "2024-06-01T00:00:00+00:00"


def _make_pref(text: str, confidence: float) -> Preference:
    return Preference(text=text, confidence=confidence, source="rule", last_seen=NOW)


def test_load_profile_from_missing_file_returns_empty(tmp_path: Path) -> None:
    """load_profile() returns an empty Profile when no profile.json exists."""
    store = tmp_path / "store"

    result = load_profile(store)

    assert result.languages == {}
    assert result.preferences == ()
    assert result.sessions_processed == 0


def test_save_then_load_round_trips_correctly(tmp_path: Path, sample_profile: Profile) -> None:
    """save_profile() then load_profile() returns a profile equal to the original."""
    store = tmp_path / "store"

    save_profile(sample_profile, store)
    loaded = load_profile(store)

    assert loaded.languages == sample_profile.languages
    assert loaded.frameworks == sample_profile.frameworks
    assert loaded.tools == sample_profile.tools
    assert loaded.sessions_processed == sample_profile.sessions_processed
    assert loaded.coding_style.indent == sample_profile.coding_style.indent
    assert len(loaded.preferences) == len(sample_profile.preferences)


def test_load_corrupted_json_falls_back_to_bak(tmp_path: Path, sample_profile: Profile) -> None:
    """load_profile() uses the .bak file when profile.json contains invalid JSON."""
    store = tmp_path / "store"
    store.mkdir()

    bak_path = store / "profile.json.bak"
    bak_path.write_text(json.dumps(_to_dict(sample_profile)), encoding="utf-8")

    (store / "profile.json").write_text("{ not valid json !!!", encoding="utf-8")

    result = load_profile(store)

    assert result.sessions_processed == sample_profile.sessions_processed


def test_load_both_corrupted_returns_empty(tmp_path: Path) -> None:
    """load_profile() returns an empty Profile when both json and bak are corrupt."""
    store = tmp_path / "store"
    store.mkdir()
    (store / "profile.json").write_text("INVALID", encoding="utf-8")
    (store / "profile.json.bak").write_text("ALSO INVALID", encoding="utf-8")

    result = load_profile(store)

    assert result.languages == {}
    assert result.sessions_processed == 0


def test_merge_profile_decays_base_then_sums() -> None:
    """Base counts are decayed (int(v*0.98)) before the session is added."""
    base = _profile_with_langs({"python": 3, "go": 5})
    other = _profile_with_langs({"python": 2, "rust": 5})

    result = merge_profile(base, other, NOW)

    assert result.languages["python"] == 4       # 3->2, +2
    assert result.languages["go"] == 4           # 5->4, not seen again
    assert result.languages["rust"] == 5         # new


def test_merge_profile_abandoned_tech_fades_to_zero() -> None:
    """Tech not seen again erodes across merges and is dropped."""
    langs = {"cobol": 3}
    for _ in range(20):
        base = _profile_with_langs(langs)
        langs = merge_profile(base, _profile_with_langs({"python": 1}), NOW).languages

    assert "cobol" not in langs
    assert langs["python"] > 0


def test_muted_round_trips(tmp_path: Path) -> None:
    """The muted list survives save -> load."""
    import dataclasses

    store = tmp_path / "store"
    store.mkdir()
    profile = dataclasses.replace(Profile.empty(NOW), muted=("correction:simplify", "lang:go"))
    save_profile(profile, store)

    assert set(load_profile(store).muted) == {"correction:simplify", "lang:go"}


def test_merge_unions_muted() -> None:
    """merge_profile() unions muted ids from both profiles (survives re-learning)."""
    import dataclasses

    base = dataclasses.replace(Profile.empty(NOW), muted=("correction:simplify",))
    other = dataclasses.replace(Profile.empty(NOW), muted=("lang:go",))

    merged = merge_profile(base, other, NOW)

    assert set(merged.muted) == {"correction:simplify", "lang:go"}


def test_merge_profile_preference_higher_confidence_wins() -> None:
    """merge_profile() keeps the preference with higher confidence on duplicate text."""
    base = _profile_with_prefs((_make_pref("root-cause analysis", 0.6),))
    other = _profile_with_prefs((_make_pref("root-cause analysis", 0.9),))

    result = merge_profile(base, other, NOW)

    matching = [p for p in result.preferences if "root-cause" in p.text.lower()]
    assert len(matching) == 1
    assert matching[0].confidence == 0.9


def test_merge_profile_cap_at_20_languages() -> None:
    """merge_profile() caps the language dict at 20 entries."""
    base_langs = {f"lang_{i}": i + 1 for i in range(15)}
    other_langs = {f"other_{i}": i + 1 for i in range(10)}

    result = merge_profile(_profile_with_langs(base_langs), _profile_with_langs(other_langs), NOW)

    assert len(result.languages) <= 20


def test_merge_profile_coding_style_from_other_wins_if_not_unknown() -> None:
    """merge_profile() uses other's coding_style when it is not 'unknown'."""
    base = _profile_with_style(CodingStyle(indent="unknown"))
    other = _profile_with_style(CodingStyle(indent="tabs", indent_size=4, test_frequency="low"))

    result = merge_profile(base, other, NOW)

    assert result.coding_style.indent == "tabs"


def test_merge_profile_base_style_kept_when_other_is_unknown() -> None:
    """merge_profile() keeps base's coding_style when other.indent is 'unknown'."""
    base = _profile_with_style(CodingStyle(indent="spaces", indent_size=2))
    other = _profile_with_style(CodingStyle(indent="unknown"))

    result = merge_profile(base, other, NOW)

    assert result.coding_style.indent == "spaces"


def test_merge_profile_sessions_processed_incremented() -> None:
    """merge_profile() adds sessions_processed from both profiles."""
    result = merge_profile(_profile_with_sessions(3), _profile_with_sessions(5), NOW)

    assert result.sessions_processed == 8


def test_profile_empty_machine_fingerprint_is_nonempty_string() -> None:
    """Profile.empty() produces a non-empty machine_fingerprint string."""
    profile = Profile.empty(NOW)

    assert isinstance(profile.machine_fingerprint, str)
    assert len(profile.machine_fingerprint) > 0


# ── helpers ──────────────────────────────────────────────────────────────────


def _base_empty() -> Profile:
    return Profile.empty(NOW)


def _profile_with_prefs(prefs: tuple[Preference, ...]) -> Profile:
    p = _base_empty()
    return Profile(
        version=p.version,
        languages=p.languages,
        frameworks=p.frameworks,
        tools=p.tools,
        preferences=prefs,
        coding_style=p.coding_style,
        last_updated=p.last_updated,
        sessions_processed=p.sessions_processed,
        machine_fingerprint=p.machine_fingerprint,
    )


def _profile_with_langs(langs: dict[str, int]) -> Profile:
    p = _base_empty()
    return Profile(
        version=p.version,
        languages=langs,
        frameworks=p.frameworks,
        tools=p.tools,
        preferences=p.preferences,
        coding_style=p.coding_style,
        last_updated=p.last_updated,
        sessions_processed=p.sessions_processed,
        machine_fingerprint=p.machine_fingerprint,
    )


def _profile_with_style(style: CodingStyle) -> Profile:
    p = _base_empty()
    return Profile(
        version=p.version,
        languages=p.languages,
        frameworks=p.frameworks,
        tools=p.tools,
        preferences=p.preferences,
        coding_style=style,
        last_updated=p.last_updated,
        sessions_processed=p.sessions_processed,
        machine_fingerprint=p.machine_fingerprint,
    )


def _profile_with_sessions(n: int) -> Profile:
    p = _base_empty()
    return Profile(
        version=p.version,
        languages=p.languages,
        frameworks=p.frameworks,
        tools=p.tools,
        preferences=p.preferences,
        coding_style=p.coding_style,
        last_updated=p.last_updated,
        sessions_processed=n,
        machine_fingerprint=p.machine_fingerprint,
    )
