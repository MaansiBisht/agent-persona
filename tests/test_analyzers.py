from __future__ import annotations


from agent_persona.analyzers.stack_detector import detect_stack
from agent_persona.analyzers.style_detector import detect_style
from agent_persona.compiler import compile_profile
from agent_persona.models import Preference, Profile

NOW = "2024-06-01T00:00:00+00:00"


# ── stack_detector.py ─────────────────────────────────────────────────────────


def test_detect_stack_python_tool_signals() -> None:
    """detect_stack() identifies python from .py file-path signals."""
    tool_signals = ["/project/main.py", "/project/utils.py"]

    result = detect_stack(tool_signals=tool_signals, commands=[], extensions={})

    assert "python" in result["languages"]
    assert result["languages"]["python"] > 0


def test_detect_stack_docker_commands() -> None:
    """detect_stack() identifies docker from command signals."""
    commands = ["docker build .", "docker run -p 8080:8080 myapp"]

    result = detect_stack(tool_signals=[], commands=commands, extensions={})

    assert "docker" in result["tools"]
    assert result["tools"]["docker"] > 0


def test_detect_stack_inflation_guard_caps_extension_matches() -> None:
    """detect_stack() caps signal matches per corpus item at 5 to prevent inflation."""
    # 200 .py extension occurrences; without capping python score would be huge
    extensions = {"py": 200}

    result = detect_stack(tool_signals=[], commands=[], extensions=extensions)

    # Each signal match is capped at 5, so total for python should be at most 5
    assert result["languages"].get("python", 0) <= 5


# ── style_detector.py ─────────────────────────────────────────────────────────


def test_detect_style_spaces_indent() -> None:
    """detect_style() sets indent='spaces' when file_signals reports spaces."""
    file_signals = {
        "indent": "spaces",
        "indent_size": 4,
        "test_file_count": 0,
        "total_file_count": 1,
    }

    style = detect_style(file_signals)

    assert style.indent == "spaces"


def test_detect_style_high_test_ratio() -> None:
    """detect_style() returns test_frequency='high' when test ratio > 0.25."""
    file_signals = {
        "indent": "unknown",
        "indent_size": 4,
        "test_file_count": 3,
        "total_file_count": 10,
    }

    style = detect_style(file_signals)

    assert style.test_frequency == "high"


def test_detect_style_zero_test_ratio_is_unknown() -> None:
    """detect_style() returns test_frequency='unknown' when there are no test files."""
    file_signals = {
        "indent": "unknown",
        "indent_size": 4,
        "test_file_count": 0,
        "total_file_count": 10,
    }

    style = detect_style(file_signals)

    assert style.test_frequency == "unknown"


# ── compiler.py ───────────────────────────────────────────────────────────────


def test_compile_profile_empty_profile_returns_empty_string() -> None:
    """compile_profile() returns '' for a profile with no stack and fewer than 2 prefs."""
    profile = Profile.empty(NOW)

    result = compile_profile(profile)

    assert result == ""


def test_compile_profile_with_stack_contains_language_names() -> None:
    """compile_profile() includes stack language names when the profile has stack data."""
    profile = _profile_with_stack({"python": 10, "typescript": 5})

    result = compile_profile(profile)

    assert "python" in result
    assert "typescript" in result


def test_compile_profile_high_confidence_pref_annotated() -> None:
    """compile_profile() appends '(high confidence)' for preferences with confidence >= 0.85."""
    high_pref = Preference(
        text="always write docstrings",
        confidence=0.9,
        source="rule",
        last_seen=NOW,
    )
    low_pref = Preference(
        text="use snake_case",
        confidence=0.7,
        source="rule",
        last_seen=NOW,
    )
    profile = _profile_with_prefs_and_stack((high_pref, low_pref))

    result = compile_profile(profile)

    assert "(high confidence)" in result
    lines = result.splitlines()
    snake_line = next((ln for ln in lines if "snake_case" in ln), "")
    assert "(high confidence)" not in snake_line


# ── helpers ──────────────────────────────────────────────────────────────────


def _profile_with_stack(languages: dict[str, int]) -> Profile:
    p = Profile.empty(NOW)
    return Profile(
        version=p.version,
        languages=languages,
        frameworks=p.frameworks,
        tools=p.tools,
        preferences=p.preferences,
        coding_style=p.coding_style,
        last_updated=p.last_updated,
        sessions_processed=p.sessions_processed,
        machine_fingerprint=p.machine_fingerprint,
    )


def _profile_with_prefs_and_stack(prefs: tuple[Preference, ...]) -> Profile:
    """Return a profile with both a stack and the given preferences so compile_profile() is meaningful."""
    p = Profile.empty(NOW)
    return Profile(
        version=p.version,
        languages={"python": 5},
        frameworks=p.frameworks,
        tools=p.tools,
        preferences=prefs,
        coding_style=p.coding_style,
        last_updated=p.last_updated,
        sessions_processed=p.sessions_processed,
        machine_fingerprint=p.machine_fingerprint,
    )
