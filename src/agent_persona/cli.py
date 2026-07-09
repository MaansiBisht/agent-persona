from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from agent_persona import __version__

console = Console()


@click.group()
@click.version_option(__version__, prog_name="agent-persona")
def cli() -> None:
    pass


@cli.command()
@click.option("--dry-run", is_flag=True, default=False)
def install(dry_run: bool) -> None:
    from agent_persona.installer import _build_hooks, install as do_install

    if dry_run:
        console.print("[bold]Hooks that would be added:[/bold]")
        for event, entries in _build_hooks().items():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    kind = hook.get("type", "?")
                    detail = hook.get("command") or hook.get("prompt", "")
                    console.print(f"  [cyan]{event}[/cyan] ({kind}): {detail}")
        return

    added = do_install()
    if added:
        console.print("[green]agent-persona hooks installed successfully.[/green]")
    else:
        console.print("[yellow]agent-persona hooks are already installed.[/yellow]")


@cli.command()
@click.option("--purge", is_flag=True, default=False, help="Also delete the profile store (~/.agent-persona).")
def uninstall(purge: bool) -> None:
    from agent_persona.installer import uninstall as do_uninstall

    removed = do_uninstall()
    if removed:
        console.print("[green]agent-persona hooks removed.[/green]")
    else:
        console.print("[yellow]No agent-persona hooks found to remove.[/yellow]")

    if purge:
        from agent_persona.profile import default_store

        store = default_store()
        if store.exists():
            shutil.rmtree(store)
            console.print(f"[green]Profile store deleted: {store}[/green]")
        else:
            console.print("[yellow]No profile store to delete.[/yellow]")


@cli.command()
def analyze() -> None:
    from agent_persona.hooks.stop_hook import run_pipeline

    with console.status("[bold green]Analyzing session..."):
        try:
            run_pipeline()
            console.print("[green]Analysis complete.[/green]")
        except Exception as exc:
            console.print(f"[red]Analysis failed: {exc}[/red]")


@cli.command()
def show() -> None:
    """Print the persona exactly as it is injected at session start."""
    from datetime import datetime, timezone

    from agent_persona.compiler import render

    content = render(datetime.now(timezone.utc).isoformat())
    if content.strip():
        console.print(content)
    else:
        console.print("[yellow]Nothing to inject — not enough profile data yet.[/yellow]")


@cli.command()
def status() -> None:
    from agent_persona.profile import load_profile

    profile = load_profile()

    table = Table(title="agent-persona status", show_header=False)
    table.add_column("Field", style="bold cyan")
    table.add_column("Value")

    table.add_row("Sessions processed", str(profile.sessions_processed))

    top_stack = (
        sorted(profile.languages.items(), key=lambda x: x[1], reverse=True)[:3]
        + sorted(profile.frameworks.items(), key=lambda x: x[1], reverse=True)[:2]
    )
    stack_str = " · ".join(name for name, _ in top_stack) if top_stack else "(none)"
    table.add_row("Top stack", stack_str)

    top_prefs = sorted(profile.preferences, key=lambda p: p.confidence, reverse=True)[:5]
    for i, pref in enumerate(top_prefs):
        label = "Preferences" if i == 0 else ""
        table.add_row(label, f"{pref.text} ({pref.confidence:.0%})")

    table.add_row("Last updated", profile.last_updated or "(never)")

    console.print(table)


@cli.command()
@click.argument("path", default=None, required=False)
@click.option("--force", is_flag=True, default=False)
def export(path: str | None, force: bool) -> None:
    from agent_persona.profile import default_store

    store = default_store()
    src = store / "profile.json"

    if not src.exists():
        console.print("[red]No profile found. Run 'agent-persona analyze' first.[/red]")
        sys.exit(1)

    dest = Path(path) if path else Path("~/agent-persona-export.json").expanduser()

    if dest.exists() and not force:
        console.print(
            f"[yellow]{dest} already exists. Use --force to overwrite.[/yellow]"
        )
        sys.exit(1)

    shutil.copy2(src, dest)
    console.print(f"[green]Profile exported to {dest}[/green]")


@cli.command("import")
@click.argument("path")
def import_profile(path: str) -> None:
    from datetime import datetime, timezone

    from agent_persona.profile import _from_dict  # type: ignore[attr-defined]
    from agent_persona.profile import (
        default_store,
        load_profile,
        merge_profile,
        save_profile,
    )

    src = Path(path)
    if not src.exists():
        console.print(f"[red]{src} not found.[/red]")
        sys.exit(1)

    try:
        incoming_data = json.loads(src.read_text(encoding="utf-8"))
        incoming = _from_dict(incoming_data)
    except Exception as exc:
        console.print(f"[red]Failed to read {src}: {exc}[/red]")
        sys.exit(1)

    store = default_store()
    local = load_profile(store)
    now = datetime.now(timezone.utc).isoformat()
    merged = merge_profile(local, incoming, now)
    save_profile(merged, store)
    console.print("[green]Profile imported and merged.[/green]")


@cli.command()
@click.option("--confirm", is_flag=True, default=False)
def reset(confirm: bool) -> None:
    if not confirm:
        console.print("[yellow]Pass --confirm to actually reset.[/yellow]")
        return

    from agent_persona.profile import default_store

    store = default_store()
    if store.exists():
        shutil.rmtree(store)
    console.print("[green]Profile store cleared.[/green]")


@cli.command()
def doctor() -> None:
    from agent_persona.installer import is_installed
    from agent_persona.profile import default_store

    checks: list[tuple[str, bool, str]] = []

    python_ok = Path(sys.executable).exists()
    checks.append(("Python executable resolves", python_ok, sys.executable))

    hooks_ok = is_installed()
    checks.append(("Hooks present in settings.json", hooks_ok, ""))

    store = default_store()
    try:
        store.mkdir(parents=True, exist_ok=True)
        test_file = store / ".write_test"
        test_file.write_text("ok")
        test_file.unlink()
        store_ok = True
    except OSError:
        store_ok = False
    checks.append(("Store directory writable", store_ok, str(store)))

    settings_path = Path("~/.claude/settings.json").expanduser()
    if settings_path.exists():
        try:
            json.loads(settings_path.read_text(encoding="utf-8"))
            settings_ok = True
        except json.JSONDecodeError:
            settings_ok = False
    else:
        settings_ok = True
    checks.append(("settings.json valid JSON", settings_ok, str(settings_path)))

    table = Table(title="agent-persona doctor", show_header=True)
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")

    for label, passed, detail in checks:
        status = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
        table.add_row(label, status, detail)

    console.print(table)


@cli.command()
def customize() -> None:
    """Interactively set manual preferences — like ChatGPT Custom Instructions."""
    from agent_persona.tui import customize as run_tui

    run_tui()


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
