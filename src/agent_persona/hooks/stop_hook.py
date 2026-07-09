from __future__ import annotations

import dataclasses
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_pipeline(store: Path | None = None) -> None:
    os.environ["AGENT_PERSONA_SKIP"] = "1"

    from agent_persona.analyzers.correction_extractor import extract_corrections
    from agent_persona.analyzers.request_pattern_extractor import extract_request_patterns
    from agent_persona.analyzers.stack_detector import detect_stack
    from agent_persona.analyzers.style_detector import detect_style
    from agent_persona.collectors.corrections import (
        append_corrections,
        collect_correction_events,
    )
    from agent_persona.collectors.file_patterns import collect_file_signals
    from agent_persona.collectors.request_patterns import (
        append_observation,
        collect_transitions,
    )
    from agent_persona.collectors.shell_history import collect_shell_history
    from agent_persona.collectors.transcript import (
        collect_transcript,
        find_unprocessed_transcripts,
        mark_processed,
    )
    from agent_persona.models import Profile
    from agent_persona.profile import (
        default_store,
        load_profile,
        merge_profile,
        save_profile,
    )

    if store is None:
        store = default_store()

    now = _now_iso()
    existing = load_profile(store)
    new_profile = existing

    claude_dir = Path("~/.claude").expanduser()
    transcripts = find_unprocessed_transcripts(claude_dir=claude_dir, state_store=store)

    # shell history and file signals are machine-wide — read once, not per transcript
    commands = collect_shell_history()
    file_signals = collect_file_signals(store)
    coding_style = detect_style(file_signals)

    for transcript_path in transcripts:
        try:
            session_id = transcript_path.stem
            project = transcript_path.parent.name
            user_messages, tool_signals = collect_transcript(transcript_path, store)

            stack = detect_stack(tool_signals, commands, file_signals.get("extensions", {}))
            transitions = collect_transitions(user_messages)
            append_observation(transitions, session_id, project, now, store)
            correction_events = collect_correction_events(transcript_path)
            append_corrections(correction_events, session_id, project, now, store)

            delta = Profile(
                version=existing.version,
                languages=stack.get("languages", {}),
                frameworks=stack.get("frameworks", {}),
                tools=stack.get("tools", {}),
                # Regex preference mining removed (unreliable — see docs/PLAN.md).
                # Preferences come from manual `customize` and, later, the LLM tier.
                preferences=(),
                coding_style=coding_style if new_profile.coding_style.indent == "unknown" else new_profile.coding_style,
                last_updated=now,
                sessions_processed=1,
                machine_fingerprint=existing.machine_fingerprint,
            )

            new_profile = merge_profile(new_profile, delta, now)
            save_profile(new_profile, store)
            mark_processed(session_id, store)
        except Exception as exc:
            print(f"agent-persona: skipping {transcript_path.stem}: {exc}", file=sys.stderr)

    request_patterns = extract_request_patterns(store, now)
    corrections = extract_corrections(store, now)
    new_profile = dataclasses.replace(
        new_profile, request_patterns=request_patterns, corrections=corrections
    )
    save_profile(new_profile, store)
    # Injection is compiled live at SessionStart (compiler.render) — Stop only
    # persists the profile; no context.md / CLAUDE.md is written here.


def main() -> None:
    try:
        raw = sys.stdin.read().strip()
        if raw:
            try:
                json.loads(raw)
            except (json.JSONDecodeError, AttributeError):
                pass
        run_pipeline()
    except Exception:
        pass


if __name__ == "__main__":
    main()
