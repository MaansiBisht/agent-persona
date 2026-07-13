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

Claude is powerful out of the box, but it starts every session not knowing you: your stack, your coding style, or how you like to be corrected. agent-persona learns that from your own Claude sessions and shell history, builds a persona on this machine, and injects it into every new session.

No configuration, no manual writing, and no API key required.

## Install

```bash
pipx install agent-persona
agent-persona run
```

`run` builds your persona and asks whether to bind it to all future sessions. Say yes and you are done.

## What it looks like

An excerpt from a real generated persona (`agent-persona show`):

```markdown
### Layer 1 - Stable Identity
- CLI-first: lives entirely in the terminal (git, ssh, shell scripts, CLI agents)
- Ships fast, verifies after: tests the published artifact rather than simulating locally
- Trusts `git log` as ground truth: inspects history after nearly every pull
- Prefers small, confirmable edits over large sweeping changes

### Layer 2 - Technical Knowledge Map
**Git** ★★★★☆
Needs: worktree workflows, multi-remote sync edge cases, history rewriting risks
Skip: what pull/stash/log do, basic branching, commit syntax

### Negative Prompt
- Never restate the user's request before acting on it.
- Never present a menu of options when asked for an opinion. Recommend one.
- Never treat typos as blockers. Infer intent and proceed.
```

Claude reads this at the start of every session, so it stops explaining basics you know, pitches answers at your level, and avoids the things that annoy you.

## What it learns

Python collects the raw data deterministically (session transcripts, tool usage, shell history, all secret-redacted). Then Claude itself, via `claude --print` using the Claude Code login you already have, synthesizes a structured persona with 8 layers:

- **Stable identity:** who you are as an engineer.
- **Knowledge map:** star ratings per technology, what to explain and what to skip.
- **Thinking style:** how you learn and what order explanations should follow.
- **Output preferences:** formats you want, formats that annoy you.
- **Decision framework:** what you optimise for when choosing between approaches.
- **Curiosity profile:** the kinds of questions you actually ask.
- **Communication:** what Claude should and should never do.
- **Current projects:** volatile work context, replaced every couple of months.

No keyword matching and no NLP heuristics: Claude reads your actual history and writes the profile.

## How it works

```
~/.claude/projects/**/*.jsonl + shell history
        |
Deterministic collectors (pure Python)
        |
claude --print
        |
~/.agent-persona/persona.md
        |
~/.claude/CLAUDE.md @import
```

Injection uses Claude Code's native `@file` import: one marker-delimited line in `~/.claude/CLAUDE.md` that Claude reads at every session start. A single Stop hook in `~/.claude/settings.json` re-runs synthesis when a session ends, so the persona grows as you work.

## Your persona

Everything lives in `~/.agent-persona/`, on this machine, as plain files you can read and edit:

```
~/.agent-persona/
├── persona.md   # your persona, the single source of truth
└── state.json   # tracks which sessions were processed
```

To move machines, copy `persona.md` across and run `agent-persona install`.

## Commands

| Command | What it does |
|---|---|
| `agent-persona run` | Scrape new sessions, synthesise persona.md, offer to bind. |
| `agent-persona show` | Print the persona exactly as Claude reads it. |
| `agent-persona install` | Bind persona.md to all future sessions and register the Stop hook. |
| `agent-persona uninstall [--purge]` | Remove binding and hook. With `--purge`, also wipe `~/.agent-persona`. |
| `agent-persona doctor` | Check install health. |

## Detach anytime

agent-persona adds one marker-delimited block to `~/.claude/CLAUDE.md` and one Stop hook. `agent-persona uninstall` removes exactly those and nothing else; your own CLAUDE.md content is never touched. Add `--purge` to wipe the persona store too.


## Privacy

- Your data never leaves this machine except the synthesis call to `claude --print`, your already-authenticated Claude Code instance.
- API keys, tokens, and passwords are redacted from every data stream before synthesis.
- No cloud, no telemetry, no accounts.

## Fallback: API key

To run synthesis headless (CI, cron) without a Claude Code session, set `ANTHROPIC_API_KEY` and it falls back to the Anthropic API:

```bash
pip install "agent-persona[api]"
export ANTHROPIC_API_KEY=sk-ant-...
agent-persona run
```

## What it does not do

- No writes to your project files or code.
- One global persona, not per-project.
- No GUI.

## Requirements

- Python 3.11+
- [Claude CLI](https://claude.ai/code) installed and authenticated
- macOS, Linux, or Windows

## License

MIT
