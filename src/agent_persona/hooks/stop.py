import json
import os
import sys


def main():
    if os.environ.get("AGENT_PERSONA_SKIP"):
        return
    os.environ["AGENT_PERSONA_SKIP"] = "1"

    # The Stop hook payload identifies the CURRENT (in-progress) session.
    # We must exclude it so a session is never marked processed after
    # only its first turn. Other concurrent in-progress sessions are
    # protected by the mtime settle window inside
    # find_unprocessed_transcripts (see TRANSCRIPT_SETTLE_SECONDS).
    session_id = None
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
        if isinstance(payload, dict):
            sid = payload.get("session_id")
            if isinstance(sid, str) and sid:
                session_id = sid
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        pass

    try:
        from pathlib import Path

        from agent_persona.collectors import (
            DEFAULT_STORE,
            PERSONA_PATH,
            find_unprocessed_transcripts,
        )
        from agent_persona.harness import run

        transcripts = find_unprocessed_transcripts(
            claude_dir=Path("~/.claude").expanduser(),
            state_store=DEFAULT_STORE,
            exclude_session_id=session_id,
        )
        if transcripts:
            status, message = run(
                store=DEFAULT_STORE,
                persona_path=PERSONA_PATH,
                exclude_session_id=session_id,
            )
            if status == "error":
                print(f"agent-persona: {message}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001 — hook must never crash the host CLI
        print(f"agent-persona: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
