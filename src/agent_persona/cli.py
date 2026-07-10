"""Click CLI: run, show, install, uninstall, doctor."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from agent_persona import __version__, harness, installer
from agent_persona.collectors import DEFAULT_STORE, PERSONA_PATH

console = Console()

STORE = DEFAULT_STORE
PERSONA = PERSONA_PATH


@click.group()
@click.version_option(version=__version__, prog_name="agent-persona")
def main() -> None:
    """Personalise Claude Code by letting Claude learn from your sessions."""


@main.command()
def run() -> None:
    """Collect new sessions and synthesize persona.md.

    After a successful synthesis, you will be asked whether to bind the
    persona to all future Claude Code sessions via ~/.claude/CLAUDE.md.
    """
    with console.status("Synthesizing persona from your sessions..."):
        status, message = harness.run(store=STORE, persona_path=PERSONA)

    if status == "updated":
        console.print(f"[green]persona.md written[/green] → {message}")
        if not installer.is_bound():
            console.print()
            bind = click.confirm(
                "Bind to all future Claude Code sessions?",
                default=False,
            )
            if bind:
                installer.install_stop_hook()
                installer.bind(PERSONA)
                console.print(
                    "[green]Bound.[/green] "
                    "persona.md will be loaded in every future session via ~/.claude/CLAUDE.md."
                )
        else:
            console.print("[dim]Already bound to Claude Code sessions.[/dim]")
    elif status == "nothing":
        console.print(f"[yellow]{message}[/yellow]")
    else:
        console.print(f"[red]error:[/red] {message}")
        sys.exit(1)


@main.command()
def show() -> None:
    """Print the current persona.md."""
    if PERSONA.exists() and PERSONA.read_text(encoding="utf-8").strip():
        console.print(PERSONA.read_text(encoding="utf-8"))
    else:
        console.print("No persona yet. Run: [bold]agent-persona run[/bold]")


@main.command()
def install() -> None:
    """Bind persona.md to all future Claude Code sessions.

    Writes a @import line into ~/.claude/CLAUDE.md and registers a Stop hook
    in ~/.claude/settings.json so the persona re-synthesizes automatically
    when sessions end.
    """
    STORE.mkdir(parents=True, exist_ok=True)
    result = installer.install(PERSONA)
    if result["claude_md"]:
        console.print("[green]Bound.[/green] persona.md will be loaded in every future session.")
    else:
        console.print("[yellow]~/.claude/CLAUDE.md binding already present.[/yellow]")
    if result["stop_hook"]:
        console.print("[green]Stop hook registered.[/green] Persona will auto-refresh on session end.")
    else:
        console.print("[yellow]Stop hook already registered.[/yellow]")
    if not PERSONA.exists():
        console.print("Run [bold]agent-persona run[/bold] to synthesize your first persona.")


@main.command()
@click.option("--purge", is_flag=True, help="Also delete ~/.agent-persona directory.")
def uninstall(purge: bool) -> None:
    """Remove the CLAUDE.md binding and Stop hook."""
    result = installer.uninstall()
    if result["claude_md"]:
        console.print("[green]Removed[/green] CLAUDE.md binding.")
    else:
        console.print("[yellow]No CLAUDE.md binding found.[/yellow]")
    if result["stop_hook"]:
        console.print("[green]Removed[/green] Stop hook.")
    else:
        console.print("[yellow]No Stop hook found.[/yellow]")

    if purge:
        if STORE.exists():
            shutil.rmtree(STORE)
            console.print(f"[green]Deleted[/green] {STORE}")
        else:
            console.print(f"[yellow]{STORE} does not exist.[/yellow]")


@main.command()
def doctor() -> None:
    """Check that everything is wired up correctly."""
    table = Table(title="agent-persona doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")

    def row(name: str, ok: bool, detail: str) -> None:
        status = "[green]PASS[/green]" if ok else "[red]FAIL[/red]"
        table.add_row(name, status, detail)

    row("Python executable", Path(sys.executable).exists(), str(sys.executable))

    # claude CLI (primary synthesis path)
    claude_bin = shutil.which("claude")
    row(
        "claude CLI",
        bool(claude_bin),
        claude_bin or "not found — install Claude Code from claude.ai/code",
    )

    # CLAUDE.md binding
    bound = installer.is_bound()
    row(
        "CLAUDE.md binding",
        bound,
        str(Path("~/.claude/CLAUDE.md").expanduser()) if bound else "run: agent-persona install",
    )

    # Stop hook
    hook_ok = installer.stop_hook_installed()
    row(
        "Stop hook",
        hook_ok,
        str(Path("~/.claude/settings.json").expanduser()) if hook_ok else "run: agent-persona install",
    )

    # Stale 0.3.x hooks (point at deleted modules; install removes them)
    legacy = installer.legacy_hooks_present()
    row(
        "No legacy 0.3.x hooks",
        not legacy,
        "run: agent-persona install (removes stale hooks)" if legacy else "clean",
    )

    # persona.md present
    row(
        "persona.md present",
        PERSONA.exists(),
        str(PERSONA) if PERSONA.exists() else "run: agent-persona run",
    )

    # Store writable
    store_ok = True
    store_detail = str(STORE)
    try:
        STORE.mkdir(parents=True, exist_ok=True)
        probe = STORE / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        store_ok = False
        store_detail = f"{STORE}: {exc}"
    row("Store writable", store_ok, store_detail)

    # settings.json valid (informational)
    settings_path = Path("~/.claude/settings.json").expanduser()
    settings_ok = True
    settings_detail = str(settings_path)
    if settings_path.exists():
        try:
            json.loads(settings_path.read_text(encoding="utf-8") or "{}")
        except (json.JSONDecodeError, OSError) as exc:
            settings_ok = False
            settings_detail = f"invalid JSON: {exc}"
    else:
        settings_detail = "not present (created on install)"
    row("settings.json valid", settings_ok, settings_detail)

    # ANTHROPIC_API_KEY (optional fallback)
    key_present = bool(
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    )
    row(
        "ANTHROPIC_API_KEY (optional)",
        True,
        "set (API fallback available)" if key_present else "not set (claude CLI will be used)",
    )

    console.print(table)


if __name__ == "__main__":
    main()
