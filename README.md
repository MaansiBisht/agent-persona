<div align="center">

<img src="assets/logo.svg" width="100" alt="agent-persona logo" />

# agent-persona

*Personalise your Claude CLI to how you actually work.*

[![PyPI](https://img.shields.io/pypi/v/agent-persona?color=blue&label=pypi)](https://pypi.org/project/agent-persona/)
[![Python](https://img.shields.io/badge/python-3.11+-blue)](#)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](#)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)](#)

</div>

---

Claude is powerful out of the box, but it starts every session not knowing you: your stack, your coding style, or how you like to be corrected. agent-persona learns that from your own Claude sessions, the files you edit, and your shell history, builds a persona on this machine, and injects it into every new session.

No configuration and no manual writing required. To set something explicitly, run `agent-persona customize`.

## Install

```bash
pipx install agent-persona
agent-persona install
```

From the next session on, it builds your persona.

## What it learns

Everything below is free and automatic (no LLM, no cost), read from your session logs, edited files, and shell history:

- **Stack:** the languages, frameworks, and tools you actually use, frequency-weighted, with tech you stop using fading over time.
- **Coding style:** indent and test frequency, sampled from files you edit.
- **Request patterns:** recurring follow-up habits (for example, after a bug fix you usually ask why it happened).
- **Corrections:** when you redirect Claude ("revert that", "too complex", "don't add that yet"), recurring redirects become guidance such as "prefer the simplest solution" or "do only what's asked".

You can also set preferences yourself with `agent-persona customize`. Manual preferences carry full confidence and are always injected first.

## How it works

A rule engine decays stale signals, drops low-confidence ones, then ranks and caps what gets injected, so Claude receives the right context rather than a dump.

Three hooks wire into `~/.claude/settings.json`:

- **SessionStart:** compiles your persona live from `profile.json` and injects it before you type.
- **Stop:** runs the analysis pipeline and updates `profile.json` when a session ends.
- **PostToolUse:** logs each file edit in the background. Never blocks your session.

agent-persona injects only through the SessionStart hook. It never writes to your `~/.claude/CLAUDE.md`.

## Your profile

Everything lives in `~/.agent-persona/`, on this machine, as plain JSON you can read and edit:

```
~/.agent-persona/
├── profile.json           # your persona, the single source of truth
├── state.json             # tracks which sessions were processed
└── history/
    └── files_edited.jsonl # rolling 90-day log of edited files
```

The persona is compiled live from `profile.json` at session start, so there is no generated file to keep in sync.

## Commands

| Command | What it does |
|---|---|
| `agent-persona install` | Register hooks and create `~/.agent-persona/`. |
| `agent-persona uninstall [--purge]` | Remove hooks. With `--purge`, also wipe the profile store. |
| `agent-persona customize` | Set what Claude should know, how it should respond, and mute learned signals. |
| `agent-persona status` | Show your current persona: stack, preferences, sessions processed. |
| `agent-persona show` | Print the persona exactly as it is injected at session start. |
| `agent-persona analyze` | Re-run analysis on demand. |
| `agent-persona export [path]` | Export your profile to move to another machine. |
| `agent-persona import [path]` | Merge an exported profile into this machine. |
| `agent-persona reset --confirm` | Wipe the profile and start fresh. |
| `agent-persona doctor` | Check install health. |

## Detach anytime

agent-persona is a layer, not a file edit, so backing out is clean:

- Mute a single learned signal with `agent-persona customize`, then "Mute / unmute learned signals".
- Remove everything with `agent-persona uninstall --purge`.

Because it never touches your own files, nothing is left behind.

## Move your persona to a new machine

```bash
# old machine
agent-persona export ~/persona.json

# new machine
agent-persona install
agent-persona import ~/persona.json
```

Profiles merge, so nothing is lost from either machine.

## What it does not do (v1)

- No cloud. Your persona never leaves this machine unless you export it.
- No writes to your `CLAUDE.md`, or to anything outside `~/.agent-persona/`.
- One global persona, not per-project.

## Requirements

- Python 3.11+
- [Claude CLI](https://claude.ai/code) installed and authenticated
- macOS, Linux, or Windows

## License

MIT
