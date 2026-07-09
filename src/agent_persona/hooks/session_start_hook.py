from __future__ import annotations

import os
import sys


def main() -> None:
    if os.environ.get("AGENT_PERSONA_SKIP"):
        return

    try:
        import platform
        import signal

        if platform.system() != "Windows":
            def _timeout_handler(signum: int, frame: object) -> None:
                sys.exit(0)

            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(5)

        from datetime import datetime, timezone

        from agent_persona.compiler import render

        content = render(datetime.now(timezone.utc).isoformat())
        if content.strip():
            print(content, end="")
    except Exception:
        pass
    finally:
        try:
            import signal as _signal
            _signal.alarm(0)
        except Exception:
            pass


if __name__ == "__main__":
    main()
