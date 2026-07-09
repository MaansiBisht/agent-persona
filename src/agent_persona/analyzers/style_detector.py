from __future__ import annotations

from agent_persona.models import CodingStyle


def detect_style(file_signals: dict) -> CodingStyle:
    indent = file_signals.get("indent", "unknown")
    indent_size = file_signals.get("indent_size", 4)
    test_file_count = file_signals.get("test_file_count", 0)
    total_file_count = file_signals.get("total_file_count", 0)

    ratio = test_file_count / max(total_file_count, 1)
    if ratio > 0.25:
        test_frequency = "high"
    elif ratio > 0.10:
        test_frequency = "medium"
    elif ratio > 0:
        test_frequency = "low"
    else:
        test_frequency = "unknown"

    return CodingStyle(
        indent=indent,
        indent_size=indent_size,
        test_frequency=test_frequency,
    )
