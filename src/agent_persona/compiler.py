from __future__ import annotations

from pathlib import Path

from agent_persona.models import Profile


def render(now: str, store: Path | None = None) -> str:
    """Compile the persona live from the stored profile — the single injection
    path, used by the SessionStart hook and `agent-persona show`."""
    from agent_persona.profile import load_profile
    from agent_persona.rules import apply_rules

    return compile_profile(apply_rules(load_profile(store), now))


_TRIGGER_LABELS = {
    "bug_fix":    "ask you to fix a bug",
    "causal_why": "ask why something happened",
    "add_test":   "ask for tests",
    "refactor":   "ask for a refactor",
    "explain":    "ask for an explanation",
}

_FOLLOWUP_LABELS = {
    "bug_fix":    "a fix",
    "causal_why": "the root cause",
    "add_test":   "tests",
    "refactor":   "a refactor",
    "explain":    "an explanation",
}

# What recurring corrections imply Claude should do differently.
_CORRECTION_GUIDANCE = {
    "revert":         "I often undo your changes — make small, confirmable edits and check before large changes.",
    "simplify":       "I often ask to simplify — prefer the simplest solution; avoid over-engineering.",
    "wrong_approach": "I often say the approach is wrong — confirm your understanding before implementing.",
    "scope":          "I often narrow scope — do only what's asked; don't add extras unprompted.",
    "redo":           "I often redirect — pause and re-confirm direction when unsure.",
}


def compile_profile(profile: Profile) -> str:
    top_languages = sorted(profile.languages.items(), key=lambda x: x[1], reverse=True)[:5]
    top_frameworks = sorted(profile.frameworks.items(), key=lambda x: x[1], reverse=True)[:3]
    top_tools = sorted(profile.tools.items(), key=lambda x: x[1], reverse=True)[:3]

    stack_tokens = (
        [name for name, _ in top_languages]
        + [name for name, _ in top_frameworks]
        + [name for name, _ in top_tools]
    )

    manual_prefs = [p for p in profile.preferences if p.source == "manual"]
    auto_prefs = [p for p in profile.preferences if p.source != "manual"]
    top_auto = sorted(auto_prefs, key=lambda p: p.confidence, reverse=True)[:8]

    has_stack = bool(stack_tokens)
    meaningful = (
        len(profile.preferences) >= 2
        or has_stack
        or bool(profile.request_patterns)
        or bool(profile.corrections)
    )
    if not meaningful:
        return ""

    sections: list[str] = []

    if has_stack:
        sections.append("**Stack:** " + " · ".join(stack_tokens))

    if manual_prefs:
        lines = ["**Your instructions:**"]
        for pref in manual_prefs:
            lines.append(f"- {pref.text}")
        sections.append("\n".join(lines))

    if top_auto:
        pref_lines = ["**Learned preferences:**"]
        for pref in top_auto:
            suffix = " (high confidence)" if pref.confidence >= 0.85 else ""
            pref_lines.append(f"- {pref.text}{suffix}")
        sections.append("\n".join(pref_lines))

    if profile.request_patterns:
        by_trigger: dict[str, list[str]] = {}
        for rp in sorted(profile.request_patterns, key=lambda p: p.confidence, reverse=True):
            for followup in rp.always_include:
                bucket = by_trigger.setdefault(rp.trigger, [])
                if followup not in bucket:
                    bucket.append(followup)
        pattern_lines = ["**How I follow up:**"]
        for trigger, followups in by_trigger.items():
            t_label = _TRIGGER_LABELS.get(trigger, trigger)
            f_label = " and ".join(_FOLLOWUP_LABELS.get(f, f) for f in followups)
            pattern_lines.append(f"- After I {t_label}, I usually want {f_label} — include it proactively.")
        sections.append("\n".join(pattern_lines))

    if profile.corrections:
        correction_lines = ["**What I often correct — avoid these:**"]
        for signal in sorted(profile.corrections, key=lambda s: s.confidence, reverse=True):
            guidance = _CORRECTION_GUIDANCE.get(signal.kind)
            if guidance:
                correction_lines.append(f"- {guidance}")
        if len(correction_lines) > 1:
            sections.append("\n".join(correction_lines))

    style = profile.coding_style
    style_tokens: list[str] = []
    if style.indent != "unknown":
        style_tokens.append(f"{style.indent_size}-{style.indent} indent")
    if style.test_frequency != "unknown":
        style_tokens.append(f"{style.test_frequency} test frequency")
    if style_tokens:
        sections.append("**Style:** " + " · ".join(style_tokens))

    if not sections:
        return ""

    return "## Your Learned Context\n\n" + "\n\n".join(sections) + "\n"
