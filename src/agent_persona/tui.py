from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from pathlib import Path

import questionary
from rich.console import Console
from rich.table import Table

from agent_persona.models import Preference, Profile
from agent_persona.profile import default_store, load_profile, save_profile

console = Console()

_STYLE = questionary.Style([
    ("qmark",       "fg:#58A6FF bold"),
    ("question",    "bold"),
    ("answer",      "fg:#3FB950 bold"),
    ("pointer",     "fg:#58A6FF bold"),
    ("highlighted", "fg:#58A6FF bold"),
    ("selected",    "fg:#3FB950"),
    ("separator",   "fg:#484F58"),
    ("instruction", "fg:#8B949E"),
])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _manual_prefs(profile: Profile) -> list[Preference]:
    return [p for p in profile.preferences if p.source == "manual"]


def _add_preference(text: str, store: Path) -> None:
    text = text.strip()
    profile = load_profile(store)
    existing_texts = {p.text.lower() for p in profile.preferences if p.source == "manual"}
    if text.lower() in existing_texts:
        console.print("[yellow]That preference already exists.[/yellow]")
        return
    new_pref = Preference(text=text, confidence=1.0, source="manual", last_seen=_now())
    updated = dataclasses.replace(
        profile,
        preferences=profile.preferences + (new_pref,),
        last_updated=_now(),
    )
    save_profile(updated, store)
    console.print(f"[green]✓ Saved:[/green] {text}")


def _view_preferences(profile: Profile) -> None:
    manual = _manual_prefs(profile)
    if not manual:
        console.print("[dim]No manual preferences yet.[/dim]")
        return
    table = Table(show_header=True, header_style="bold cyan", box=None)
    table.add_column("#", style="dim", width=3)
    table.add_column("Preference")
    for i, p in enumerate(manual, 1):
        table.add_row(str(i), p.text)
    console.print(table)


def _remove_preferences(store: Path) -> None:
    profile = load_profile(store)
    manual = _manual_prefs(profile)
    if not manual:
        console.print("[dim]No manual preferences to remove.[/dim]")
        return
    to_remove = questionary.checkbox(
        "Select preferences to remove (space to toggle, enter to confirm):",
        choices=[p.text for p in manual],
        style=_STYLE,
    ).ask()
    if not to_remove:
        return
    remove_set = set(to_remove)
    updated = dataclasses.replace(
        profile,
        preferences=tuple(p for p in profile.preferences if p.text not in remove_set),
        last_updated=_now(),
    )
    save_profile(updated, store)
    for text in to_remove:
        console.print(f"[red]✗ Removed:[/red] {text}")


def _learned_signals(profile: Profile) -> list[tuple[str, str]]:
    """(signal_id, label) for every auto-learned signal the user can mute."""
    from agent_persona.rules import signal_id

    out: list[tuple[str, str]] = []
    for name in sorted(profile.languages, key=lambda k: profile.languages[k], reverse=True):
        out.append((f"lang:{name}", f"stack · {name}"))
    for name in sorted(profile.frameworks, key=lambda k: profile.frameworks[k], reverse=True):
        out.append((f"framework:{name}", f"stack · {name}"))
    for name in sorted(profile.tools, key=lambda k: profile.tools[k], reverse=True):
        out.append((f"tool:{name}", f"stack · {name}"))
    for rp in profile.request_patterns:
        out.append((signal_id(rp), f"follow-up · {rp.trigger}"))
    for c in profile.corrections:
        out.append((signal_id(c), f"correction · {c.kind}"))
    for p in profile.preferences:
        if p.source != "manual":
            out.append((signal_id(p), f"learned pref · {p.text}"))
    return out


def _manage_learned(store: Path) -> None:
    profile = load_profile(store)
    signals = _learned_signals(profile)
    if not signals:
        console.print("[dim]No learned signals yet — nothing to mute.[/dim]")
        return
    muted = set(profile.muted)
    choices = [
        questionary.Choice(label, value=sid, checked=(sid in muted))
        for sid, label in signals
    ]
    selected = questionary.checkbox(
        "Checked = muted (never injected). Toggle to mute/unmute:",
        choices=choices,
        style=_STYLE,
    ).ask()
    if selected is None:
        return
    updated = dataclasses.replace(
        profile, muted=tuple(dict.fromkeys(selected)), last_updated=_now()
    )
    save_profile(updated, store)
    console.print(f"[green]Updated — {len(updated.muted)} signal(s) muted.[/green]")


def customize(store: Path | None = None) -> None:
    store = store or default_store()

    console.print()
    console.print("[bold]Customize your persona[/bold]")
    console.print("[dim]Manual preferences are injected with full confidence into every session.[/dim]")
    console.print()

    while True:
        profile = load_profile(store)
        count = len(_manual_prefs(profile))
        count_label = f" [dim]({count} saved)[/dim]" if count else ""

        action = questionary.select(
            f"What would you like to do?{count_label}",
            choices=[
                questionary.Choice("Add — what Claude should know about you", value="about"),
                questionary.Choice("Add — how you want Claude to respond",     value="respond"),
                questionary.Separator(),
                questionary.Choice("View my manual preferences",  value="view"),
                questionary.Choice("Remove a preference",         value="remove"),
                questionary.Choice("Mute / unmute learned signals", value="manage"),
                questionary.Separator(),
                questionary.Choice("Done", value="done"),
            ],
            style=_STYLE,
        ).ask()

        if action is None or action == "done":
            break

        console.print()

        if action == "about":
            console.print('[dim]e.g. "I\'m a senior backend engineer", "I work in fintech", "I prefer concise answers"[/dim]')
            text = questionary.text("What should Claude know about you?", style=_STYLE).ask()
            if text and text.strip():
                _add_preference(text, store)

        elif action == "respond":
            console.print('[dim]e.g. "always show tradeoffs", "use bullet points", "never repeat what the code already says in comments"[/dim]')
            text = questionary.text("How do you want Claude to respond?", style=_STYLE).ask()
            if text and text.strip():
                _add_preference(text, store)

        elif action == "view":
            _view_preferences(load_profile(store))

        elif action == "remove":
            _remove_preferences(store)

        elif action == "manage":
            _manage_learned(store)

        console.print()

    console.print("[green]Done. Changes take effect from the next session.[/green]")
