from __future__ import annotations

import pytest

from agent_persona.models import CodingStyle, Preference, Profile


@pytest.fixture
def sample_profile() -> Profile:
    """A Profile with known data suitable for assertion in tests."""
    prefs = (
        Preference(text="root-cause analysis", confidence=0.8, source="rule", last_seen="2024-01-01T00:00:00+00:00"),
        Preference(text="immutable defaults", confidence=0.75, source="rule", last_seen="2024-01-01T00:00:00+00:00"),
    )
    style = CodingStyle(indent="spaces", indent_size=4, test_frequency="high")
    return Profile(
        version=1,
        languages={"python": 10, "typescript": 5},
        frameworks={"fastapi": 3, "react": 2},
        tools={"docker": 4, "git": 6},
        preferences=prefs,
        coding_style=style,
        last_updated="2024-01-01T00:00:00+00:00",
        sessions_processed=3,
        machine_fingerprint="abc123def456",
    )
