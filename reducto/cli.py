"""reducto CLI — Typer entrypoint."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from reducto import __version__
from reducto.config import apply_env, load_config
from reducto.git_safety import GitSafety
from reducto.models import AppConfig
from reducto.reporter import Reporter
from reducto.services import App
from reducto.session import SessionStore

app = typer.Typer(
    name="reducto",
    help="Semantic code compression engine",
    no_args_is_help=True,
)

_cfg: AppConfig | None = None


def _get_cfg(
    config: Path | None, verbose: bool, model: str, prefer_local: bool, prefer_remote: bool
) -> AppConfig:
    global _cfg
    cfg = load_config(str(config) if config else None)
    cfg.verbose = verbose or cfg.verbose
    if model:
        cfg.model = model
    if prefer_remote:
        cfg.prefer_local = False
    elif prefer_local is not None:
        cfg.prefer_local = prefer_local
    _cfg = apply_env(cfg)
    return _cfg


def _resolve_repo(path: Path) -> str:
    """Resolve to a directory or exit cleanly — commands operate on a repo, not a file."""
    p = path.resolve()
    if not p.is_dir():
        typer.echo(f"Not a directory: {p}", err=True)
        raise typer.Exit(2)
    return str(p)


def _check_git(path: str, cfg: AppConfig) -> None:
    git = GitSafety(path)
    if not git.is_repo() or git.is_clean():
        return
    typer.echo("Warning: uncommitted changes detected.")
    if cfg.pre_approve:
        return
    if not typer.confirm("Continue anyway?", default=False):
        raise typer.Exit(1)


def _run(coro):
    return asyncio.run(coro)


@app.command()
def analyze(
    path: Path = typer.Argument(Path("."), help="Repository path"),
    config: Path | None = typer.Option(None, "--config", "-c"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    report: bool = typer.Option(False, "--report"),
    model: str = typer.Option("", "--model"),
    prefer_local: bool = typer.Option(True, "--prefer-local"),
    prefer_remote: bool = typer.Option(False, "--prefer-remote"),
):
    """Scan for complexity hotspots."""
    cfg = _get_cfg(config, verbose, model, prefer_local, prefer_remote)
    svc = App(_resolve_repo(path), cfg)
    result = _run(svc.analyze(str(path)))
    typer.echo(
        f"Files: {result.total_files}  Symbols: {result.total_symbols}  Hotspots: {len(result.hotspots)}"
    )
    if report:
        p = Reporter(cfg).generate_baseline(result)
        typer.echo(f"Baseline report: {p}")


@app.command()
def deduplicate(
    path: Path = typer.Argument(Path(".")),
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes"),
    report: bool = typer.Option(False, "--report"),
    config: Path | None = typer.Option(None, "--config", "-c"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    model: str = typer.Option("", "--model"),
    prefer_remote: bool = typer.Option(False, "--prefer-remote"),
):
    """Find duplicate code blocks and propose shared utility modules (suggestion only — does not rewrite call sites)."""
    cfg = _get_cfg(config, verbose, model, True, prefer_remote)
    cfg.pre_approve = yes
    if not dry_run:
        _check_git(str(path), cfg)
    svc = App(_resolve_repo(path), cfg)
    plan = _run(svc.deduplicate(str(path)))
    typer.echo(plan.description)
    if dry_run:
        p = Reporter(cfg).generate_dry_run(plan, "deduplicate", str(path))
        typer.echo(f"Dry run report: {p}")
        return
    if not yes and not typer.confirm(f"Apply {len(plan.changes)} change(s)?", default=False):
        raise typer.Exit(0)
    result = svc.apply_plan(plan)
    typer.echo("Applied." if result.success else f"Failed: {result.error}")
    if report and result.success:
        Reporter(cfg).generate(result)


@app.command()
def idiomatize(
    path: Path = typer.Argument(Path(".")),
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes"),
    config: Path | None = typer.Option(None, "--config", "-c"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    model: str = typer.Option("", "--model"),
):
    """Rewrite code to idiomatic Python (e.g. list comprehensions)."""
    cfg = _get_cfg(config, verbose, model, True, False)
    cfg.pre_approve = yes
    if not dry_run:
        _check_git(str(path), cfg)
    svc = App(_resolve_repo(path), cfg)
    plan = _run(svc.idiomatize(str(path)))
    typer.echo(plan.description)
    if dry_run:
        Reporter(cfg).generate_dry_run(plan, "idiomatize", str(path))
        return
    if not yes and not typer.confirm(f"Apply {len(plan.changes)} change(s)?", default=False):
        raise typer.Exit(0)
    result = svc.apply_plan(plan)
    typer.echo("Applied." if result.success else f"Failed: {result.error}")


_PATTERNS = ("factory", "strategy", "observer", "singleton")


@app.command()
def pattern(
    pattern_name: str = typer.Argument("", help="factory|strategy|observer|singleton"),
    path: Path = typer.Argument(Path(".")),
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes"),
    config: Path | None = typer.Option(None, "--config", "-c"),
):
    """Apply or suggest a design pattern (factory|strategy|observer|singleton)."""
    if pattern_name and pattern_name.lower() not in _PATTERNS:
        typer.echo(
            f"Unknown pattern '{pattern_name}'. Choose from: {', '.join(_PATTERNS)}", err=True
        )
        raise typer.Exit(2)
    cfg = _get_cfg(config, False, "", True, False)
    cfg.pre_approve = yes
    if not dry_run:
        _check_git(str(path), cfg)
    svc = App(_resolve_repo(path), cfg)
    plan = _run(svc.pattern(pattern_name, str(path)))
    typer.echo(plan.description)
    if dry_run:
        Reporter(cfg).generate_dry_run(plan, "pattern", str(path))
        return
    if not yes and plan.changes and not typer.confirm("Apply changes?", default=False):
        raise typer.Exit(0)
    if plan.changes:
        svc.apply_plan(plan)


@app.command()
def check(
    path: Path = typer.Argument(Path(".")),
    config: Path | None = typer.Option(None, "--config", "-c"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Report naming, function-length, and cyclomatic-complexity issues."""
    cfg = _get_cfg(config, verbose, "", True, False)
    svc = App(_resolve_repo(path), cfg)
    result = _run(svc.check(str(path)))
    typer.echo(
        f"Issues: {result['total_issues']} (critical={result['critical']}, warning={result['warning']})"
    )


@app.command()
def apply(
    session_id: str = typer.Argument(..., help="Session ID from a prior command"),
    path: Path = typer.Argument(Path(".")),
    yes: bool = typer.Option(False, "--yes"),
    config: Path | None = typer.Option(None, "--config", "-c"),
):
    """Apply a previously saved plan by session ID."""
    cfg = _get_cfg(config, False, "", True, False)
    cfg.pre_approve = yes
    root = Path(_resolve_repo(path))
    store = SessionStore(storage_dir=str(root / ".reducto" / "sessions"))
    plan = store.load_plan(session_id)
    if not plan:
        typer.echo(f"Session not found: {session_id}", err=True)
        raise typer.Exit(1)
    svc = App(str(root), cfg)
    if not yes and not typer.confirm(f"Apply {len(plan.changes)} change(s)?", default=False):
        raise typer.Exit(0)
    result = svc.apply_plan(plan)
    typer.echo("Success" if result.success else result.error)


@app.command("report")
def report_cmd(
    session_id: str = typer.Argument("", help="Session ID or empty for latest"),
    config: Path | None = typer.Option(None, "--config", "-c"),
):
    """Print a saved report (latest, or the given session ID)."""
    cfg = _get_cfg(config, False, "", True, False)
    try:
        text = Reporter(cfg).load_latest(session_id)
    except FileNotFoundError:
        typer.echo("No report found. Run a command with --report first.", err=True)
        raise typer.Exit(1) from None
    typer.echo(text)


sessions_app = typer.Typer(help="Manage refactoring sessions")
app.add_typer(sessions_app, name="sessions")


def _session_store(path: Path) -> SessionStore:
    return SessionStore(storage_dir=str(path.resolve() / ".reducto" / "sessions"))


@sessions_app.command("list")
def sessions_list(path: Path = typer.Option(Path("."), "--path", "-C", help="Repository path")):
    """List saved refactoring sessions."""
    store = _session_store(path)
    items = store.list_sessions()
    if not items:
        typer.echo("No sessions in .reducto/sessions/")
        return
    for s in items:
        typer.echo(
            f"{s.session_id}  {s.command_type}  {s.change_count} changes  {s.created_at.isoformat()[:19]}"
        )


@sessions_app.command("show")
def sessions_show(
    session_id: str,
    path: Path = typer.Option(Path("."), "--path", "-C", help="Repository path"),
):
    """Show the changes in a saved session."""
    plan = _session_store(path).load_plan(session_id)
    if not plan:
        typer.echo("Not found", err=True)
        raise typer.Exit(1)
    typer.echo(f"{plan.description}\nChanges: {len(plan.changes)}")
    for i, c in enumerate(plan.changes, 1):
        typer.echo(f"  {i}. {c.path} — {c.description}")


@sessions_app.command("cleanup")
def sessions_cleanup(
    days: int = typer.Option(7, help="Delete sessions older than N days"),
    path: Path = typer.Option(Path("."), "--path", "-C", help="Repository path"),
):
    """Delete sessions older than N days."""
    n = _session_store(path).cleanup_old_sessions(days)
    typer.echo(f"Deleted {n} session(s)")


@app.command()
def version():
    """Show the reducto version."""
    typer.echo(f"reducto {__version__}")


def main():
    app()


if __name__ == "__main__":
    main()
