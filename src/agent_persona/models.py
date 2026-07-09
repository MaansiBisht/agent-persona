from __future__ import annotations

import hashlib
import os
import socket
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Preference:
    text: str
    confidence: float
    source: Literal["rule", "llm", "manual"]
    last_seen: str  # ISO 8601 UTC


@dataclass(frozen=True)
class RequestPattern:
    trigger: str                       # intent tag, e.g. "bug_fix"
    always_include: tuple[str, ...]    # followup tags the user reliably wants next
    confidence: float
    seen_count: int
    last_seen: str  # ISO 8601 UTC


@dataclass(frozen=True)
class CorrectionSignal:
    kind: str            # taxonomy: revert | simplify | wrong_approach | scope | redo
    count: int           # distinct sessions in which it occurred
    confidence: float
    last_seen: str       # ISO 8601 UTC


@dataclass(frozen=True)
class CodingStyle:
    indent: Literal["spaces", "tabs", "unknown"] = "unknown"
    indent_size: int = 4
    test_frequency: Literal["high", "medium", "low", "unknown"] = "unknown"


@dataclass(frozen=True)
class Profile:
    version: int
    languages: dict[str, int]
    frameworks: dict[str, int]
    tools: dict[str, int]
    preferences: tuple[Preference, ...]
    coding_style: CodingStyle
    last_updated: str  # ISO 8601 UTC
    sessions_processed: int
    machine_fingerprint: str
    request_patterns: tuple[RequestPattern, ...] = ()
    corrections: tuple[CorrectionSignal, ...] = ()
    muted: tuple[str, ...] = ()  # signal ids the user muted (see rules.signal_id)

    @staticmethod
    def empty(now: str) -> "Profile":
        fingerprint = hashlib.sha256(
            f"{os.getenv('USER', 'unknown')}@{socket.gethostname()}".encode()
        ).hexdigest()[:12]
        return Profile(
            version=1,
            languages={},
            frameworks={},
            tools={},
            preferences=(),
            coding_style=CodingStyle(),
            last_updated=now,
            sessions_processed=0,
            machine_fingerprint=fingerprint,
            request_patterns=(),
            corrections=(),
        )
