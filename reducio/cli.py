"""reducio CLI — Typer entrypoint."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from pydantic import ValidationError

from reducio import __version__
from reducio.analysis import analysis_configuration, analyze_files
from reducio.compare import CompareError, compare_revisions
from reducio.config import ConfigError, apply_env, load_config
from reducio.git_safety import GitSafety
from reducio.models import (
    AnalysisDiagnostic,
    AppConfig,
    CompareResult,
    HistoryResult,
    RefactorPlan,
    RefactorResult,
)
from reducio.plan_review import plan_preview, terminal_text, validate_plan
from reducio.progress import progress
from reducio.reporter import Reporter
from reducio.session import SessionStore
from reducio.storage import StorageError, validate_session_id
from reducio.visual_report import ReportError, ReportFormat, write_reports

if TYPE_CHECKING:
    from reducio.services import App


def _new_app(root: str, cfg: AppConfig) -> App:
    # Load optional model infrastructure only after the first progress message.
    from reducio.services import App

    try:
        return App(root, cfg)
    except StorageError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from None


app = typer.Typer(
    name="reducio",
    help="Semantic code compression engine",
    no_args_is_help=True,
)


def _get_cfg(
    config: Path | None,
    verbose: bool | None = None,
    model: str | None = None,
    llm_api: str | None = None,
    llm_base_url: str | None = None,
    check_fail_on: str | None = None,
    compare_fail_on: str | None = None,
    history_limit: int | None = None,
    history_path_aliases: list[str] | None = None,
) -> AppConfig:
    try:
        cfg = apply_env(load_config(str(config) if config is not None else None))
        overrides = {
            key: value
            for key, value in (
                ("verbose", verbose),
                ("model", model),
                ("llm_api", llm_api),
                ("llm_base_url", llm_base_url),
                ("check_fail_on", check_fail_on),
                ("compare_fail_on", compare_fail_on),
                ("history_limit", history_limit),
                ("history_path_aliases", history_path_aliases),
            )
            if value is not None
        }
        return AppConfig.model_validate(cfg.model_dump() | overrides)
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from None
    except ValidationError:
        typer.echo("Invalid configuration: check API format and severity threshold.", err=True)
        raise typer.Exit(2) from None


def _is_interactive() -> bool:
    unattended = os.environ.get("CI", "").strip().lower() not in ("", "0", "false", "no", "off")
    return not unattended and sys.stdin.isatty()


def _require_approval(yes: bool) -> None:
    if not yes and not _is_interactive():
        typer.echo(
            "Non-interactive application requires --yes; use --dry-run to review a proposal.",
            err=True,
        )
        raise typer.Exit(1)


def _resolve_repo(path: Path) -> str:
    """Resolve to a directory or exit cleanly — commands operate on a repo, not a file."""
    p = path.resolve()
    if not p.is_dir():
        typer.echo(f"Not a directory: {p}", err=True)
        raise typer.Exit(2)
    return str(p)


def _check_git(path: str, yes: bool) -> None:
    git = GitSafety(path)
    if not git.is_repo() or git.is_clean():
        return
    typer.echo("Warning: uncommitted changes detected.")
    if yes:
        return
    _require_approval(False)
    if not typer.confirm("Continue anyway?", default=False):
        raise typer.Exit(1)


def _run(coro):
    try:
        return asyncio.run(coro)
    except OSError, StorageError:
        typer.echo(
            "Cannot read source or save the plan; check paths and storage permissions.", err=True
        )
        raise typer.Exit(1) from None


def _show_plan(plan: RefactorPlan) -> None:
    typer.echo(terminal_text(plan_preview(plan)))
    for diagnostic in plan.diagnostics:
        typer.echo(
            terminal_text(f"{diagnostic.severity}: {diagnostic.file}: {diagnostic.message}"),
            err=True,
        )


def _require_complete(plan: RefactorPlan) -> None:
    if not plan.complete or any(d.severity == "error" for d in plan.diagnostics):
        typer.echo("Plan is incomplete; no changes can be applied.", err=True)
        raise typer.Exit(1)


def _has_changes(plan: RefactorPlan, cfg=None, path=None, output_dir=None, report=False) -> bool:
    if report and (not plan.complete or any(d.severity == "error" for d in plan.diagnostics)):
        _finish_apply(
            RefactorResult(
                session_id=plan.session_id,
                success=False,
                changes=[],
                tests_passed=False,
                error="Plan is incomplete or failed preflight",
            ),
            cfg,
            path,
            output_dir,
            report,
        )
    _require_complete(plan)
    if not plan.changes:
        typer.echo("No changes to apply.")
        return False
    return True


def _finish_apply(result, cfg, path, output_dir, report):
    if report:
        try:
            typer.echo(f"Apply report: {Reporter(cfg, output_dir, target=path).generate(result)}")
        except (OSError, StorageError) as error:
            state = "Changes applied" if result.success else "Application failed"
            typer.echo(f"{state}; report failed: {error}", err=True)
            raise typer.Exit(1) from None
    _show_apply_result(result)


def _show_apply_result(result: RefactorResult) -> None:
    typer.echo(f"Tests: {result.test_status}; recovery: {result.recovery_status}.")
    if result.backup_location:
        typer.echo(f"Recovery backup: {result.backup_location}")
    for error in result.recovery_errors:
        typer.echo(error, err=True)
    if result.test_status in ("failed", "error") and result.test_output:
        typer.echo(terminal_text(result.test_output), err=True)
    if not result.success:
        typer.echo(
            f"Failed: {result.error or 'Application failed without an error detail.'}", err=True
        )
        raise typer.Exit(1)
    typer.echo("Applied.")


def _report_dir(path: Path, output_dir: Path | None) -> Path:
    return output_dir if output_dir is not None else path.resolve() / ".reducio"


def _dry_run_report(
    plan: RefactorPlan, cfg: AppConfig, command: str, path: Path, output_dir: Path | None = None
) -> None:
    try:
        report = Reporter(cfg, output_dir, target=path).generate_dry_run(plan, command, str(path))
    except (OSError, StorageError) as error:
        typer.echo(f"Report failed: {error}", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"Dry run report: {report}")
    _require_complete(plan)


def _review_and_apply(
    svc,
    plan,
    cfg,
    path,
    output_dir,
    report,
    yes,
    run_tests,
    quiet,
    *,
    dry_run=False,
    command="apply",
):
    _show_plan(plan)
    if dry_run:
        _dry_run_report(plan, cfg, command, path, output_dir)
        return
    if not _has_changes(plan, cfg, path, output_dir, report):
        return
    _check_git(str(path.resolve()), yes)
    _require_approval(yes)
    if not yes and not typer.confirm(f"Apply {len(plan.changes)} change(s)?", default=False):
        raise typer.Exit(0)
    with progress("Applying changes and validating...", quiet=quiet):
        result = svc.apply_plan(plan, run_tests=run_tests)
    _finish_apply(result, cfg, path, output_dir, report)


@app.command()
def analyze(
    path: Path = typer.Argument(Path("."), help="Repository path"),
    config: Path | None = typer.Option(None, "--config", "-c"),
    verbose: bool | None = typer.Option(None, "--verbose/--no-verbose", "-v"),
    report: bool = typer.Option(False, "--report", "-r"),
    format: ReportFormat = typer.Option(
        ReportFormat.MARKDOWN, "--format", help="Format used with --report"
    ),
    output_dir: Path | None = typer.Option(
        None, "--output-dir", help="Report directory (default: TARGET/.reducio)"
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Hide progress, not results or errors"),
):
    """Scan for complexity hotspots."""
    cfg = _get_cfg(config, verbose)
    with progress("Preparing analysis...", quiet=quiet):
        svc = _new_app(_resolve_repo(path), cfg)
        result = _run(svc.analyze(str(path)))
    typer.echo(
        f"Files: {result.total_files}  Symbols: {result.total_symbols}  Hotspots: {len(result.hotspots)}"
    )
    if cfg.verbose:
        if result.hotspots:
            for h in result.hotspots[:20]:
                typer.echo(
                    f"{h.file}:{h.line}  {h.symbol}  "
                    f"cyclomatic={h.cyclomatic_complexity}  cognitive={h.cognitive_complexity}"
                )
        else:
            th = cfg.complexity_thresholds.cyclomatic_complexity
            typer.echo(f"No hotspots (cyclomatic >= {th})")
    if report:
        with progress("Generating analysis reports...", quiet=quiet):
            _write_analysis_reports(result, _report_dir(path, output_dir), format)
    for diagnostic in result.diagnostics:
        typer.echo(
            f"Metrics unavailable: {diagnostic.file}:{diagnostic.line or 1}: {diagnostic.message}",
            err=True,
        )
    if not result.complete:
        raise typer.Exit(1)


def _write_analysis_reports(result, output_dir: Path, format: ReportFormat) -> None:
    try:
        for path in write_reports(result, output_dir, format):
            label = (
                "History"
                if isinstance(result, HistoryResult)
                else "Comparison" if isinstance(result, CompareResult) else "Baseline"
            )
            typer.echo(f"{label} report: {path}")
    except (ReportError, OSError, StorageError) as error:
        typer.echo(f"Report failed: {error}", err=True)
        raise typer.Exit(1) from None


@app.command()
def compare(
    path: Path = typer.Argument(Path("."), help="Git repository or source subdirectory"),
    base: str | None = typer.Option(
        None, "--base", help="Base revision (exact ref, not an implicit merge base)"
    ),
    head: str | None = typer.Option(
        None, "--head", help="Head revision (default HEAD); working-tree edits are ignored"
    ),
    against: str | None = typer.Option(
        None, "--against", help="Compare from REF's merge base with HEAD; refs are not fetched"
    ),
    worktree: bool = typer.Option(
        False,
        "--worktree",
        help="Measure current files, including nonignored untracked Python files",
    ),
    fail_on: str | None = typer.Option(None, "--fail-on", help="none, new-hotspots or regressions"),
    annotations: str | None = typer.Option(
        None, "--annotations", help="github: emit up to ten Actions warnings"
    ),
    report: bool = typer.Option(False, "--report", "-r"),
    format: ReportFormat = typer.Option(
        ReportFormat.MARKDOWN, "--format", help="Format used with --report"
    ),
    output_dir: Path | None = typer.Option(None, "--output-dir"),
    config: Path | None = typer.Option(None, "--config", "-c"),
    verbose: bool | None = typer.Option(None, "--verbose/--no-verbose", "-v"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Hide progress, not results or errors"),
):
    """Compare changed Python files; committed revisions by default, gates opt-in."""
    if (
        bool(base) == bool(against)
        or head is not None
        and (worktree or against)
        or annotations not in (None, "github")
    ):
        typer.echo(
            "Choose --base or --against; --head cannot accompany --against/--worktree. Annotations: github.",
            err=True,
        )
        raise typer.Exit(2)
    cfg = _get_cfg(config, verbose, compare_fail_on=fail_on)
    root = _resolve_repo(path)
    try:
        with progress("Preparing revision comparison...", quiet=quiet):
            result = compare_revisions(
                root, base, head or "HEAD", cfg, against=against, worktree=worktree
            )
    except CompareError as error:
        empty = analyze_files([], cfg, str(path))
        result = CompareResult(
            scope=str(path),
            base_revision=base or against or "",
            head_revision=head or "HEAD",
            head_source="worktree" if worktree else "commit",
            gate_threshold=cfg.compare_fail_on,
            before=empty,
            after=empty,
            configuration=analysis_configuration(cfg),
            diagnostics=[AnalysisDiagnostic(file=str(path), message=str(error))],
        )
    counts = result.counts
    typer.echo(
        f"Changed Python files: {len(result.files)}  Improved: {counts['improved']}  "
        f"Regressed: {counts['regressed']}  Mixed: {counts['mixed']}  "
        f"Added: {counts['added']}  Removed: {counts['removed']}"
    )
    if not result.files and result.complete:
        typer.echo("No Python changes in the selected scope.")
    if cfg.verbose:
        for change in result.changes:
            function = change.after or change.before
            assert function is not None
            typer.echo(
                f"{function.file!r}:{function.line} {function.qualified_name} "
                f"{change.status} CC delta={change.cyclomatic_delta} cognitive delta={change.cognitive_delta}"
            )
    if report:
        with progress("Generating comparison reports...", quiet=quiet):
            _write_analysis_reports(result, _report_dir(path, output_dir), format)
    for diagnostic in result.diagnostics + result.before.diagnostics + result.after.diagnostics:
        typer.echo(f"Comparison incomplete: {diagnostic.file!r}: {diagnostic.message!r}", err=True)
    if annotations:
        from reducio.annotations import github_annotations

        for message in github_annotations(result):
            typer.echo(message)
    typer.echo(
        f"Comparison gate: {result.gate_threshold}; {'unavailable' if not result.complete else 'failed' if result.gate_failed else 'disabled' if result.gate_threshold == 'none' else 'passed'}"
    )
    if not result.complete or result.gate_failed:
        raise typer.Exit(1)


@app.command()
def history(
    path: Path = typer.Argument(Path(".")),
    ref: str = typer.Option("HEAD", "--ref", help="Newest commit; history follows first parents"),
    limit: int | None = typer.Option(
        None, "--limit", min=1, help="Commit limit (default 100; configurable)"
    ),
    path_alias: list[str] | None = typer.Option(
        None,
        "--path-alias",
        help="Former source root, repository-relative; repeat in fallback order",
    ),
    report: bool = typer.Option(False, "--report", "-r"),
    format: ReportFormat = typer.Option(ReportFormat.MARKDOWN, "--format"),
    output_dir: Path | None = typer.Option(None, "--output-dir"),
    config: Path | None = typer.Option(None, "--config", "-c"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
):
    """Rebuild historical metrics; old gaps are warnings, an incomplete head fails."""
    from reducio.history import history_revisions

    cfg = _get_cfg(config, history_limit=limit, history_path_aliases=path_alias or None)
    root = _resolve_repo(path)
    try:
        with progress("Preparing historical analysis...", quiet=quiet):
            result = history_revisions(root, ref, cfg)
    except CompareError as error:
        typer.echo(f"History unavailable: {str(error)!r}", err=True)
        raise typer.Exit(1) from None
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from None
    gaps = sum(not s.measurement.complete for s in result.snapshots)
    typer.echo(
        f"Snapshots: {len(result.snapshots)}  Historical gaps: {gaps}  Unique blobs analyzed: {result.unique_blobs_analyzed}"
    )
    if report:
        with progress("Generating historical reports...", quiet=quiet):
            _write_analysis_reports(result, _report_dir(path, output_dir), format)
    if gaps:
        typer.echo(
            "Unavailable snapshots are gaps, not zero complexity; inspect history diagnostics.",
            err=True,
        )
    if not result.head_complete:
        typer.echo("Latest snapshot is incomplete; dashboard must not be published.", err=True)
        raise typer.Exit(1)


@app.command()
def deduplicate(
    path: Path = typer.Argument(Path(".")),
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes"),
    run_tests: bool = typer.Option(
        False, "--run-tests", help="Run target tests after edits; restore on failure"
    ),
    report: bool = typer.Option(False, "--report"),
    output_dir: Path | None = typer.Option(None, "--output-dir"),
    config: Path | None = typer.Option(None, "--config", "-c"),
    verbose: bool | None = typer.Option(None, "--verbose/--no-verbose", "-v"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Hide progress, not results or errors"),
):
    """Find duplicate code blocks and propose shared utility modules (suggestion only — does not rewrite call sites)."""
    cfg = _get_cfg(config, verbose)
    root = _resolve_repo(path)
    with progress("Preparing duplicate detection...", quiet=quiet):
        svc = _new_app(root, cfg)
        plan = _run(svc.deduplicate(str(path)))
    _review_and_apply(
        svc,
        plan,
        cfg,
        path,
        output_dir,
        report,
        yes,
        run_tests,
        quiet,
        dry_run=dry_run,
        command="deduplicate",
    )


@app.command()
def idiomatize(
    path: Path = typer.Argument(Path(".")),
    dry_run: bool = typer.Option(False, "--dry-run"),
    output_dir: Path | None = typer.Option(None, "--output-dir"),
    allow_fallback: bool = typer.Option(
        False, "--allow-fallback", help="Allow heuristics if the selected model fails"
    ),
    yes: bool = typer.Option(False, "--yes"),
    report: bool = typer.Option(False, "--report"),
    run_tests: bool = typer.Option(
        False, "--run-tests", help="Run target tests after edits; restore on failure"
    ),
    config: Path | None = typer.Option(None, "--config", "-c"),
    verbose: bool | None = typer.Option(None, "--verbose/--no-verbose", "-v"),
    llm_api: str | None = typer.Option(None, "--llm-api", help="openai or anthropic"),
    llm_base_url: str | None = typer.Option(None, "--llm-base-url", help="API root including /v1"),
    model: str | None = typer.Option(None, "--model"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Hide progress, not results or errors"),
):
    """Rewrite code to idiomatic Python (e.g. list comprehensions)."""
    cfg = _get_cfg(config, verbose, model, llm_api, llm_base_url)
    root = _resolve_repo(path)
    with progress("Preparing idiom proposals...", quiet=quiet):
        svc = _new_app(root, cfg)
        plan = _run(svc.idiomatize(str(path), allow_fallback=allow_fallback))
    _review_and_apply(
        svc,
        plan,
        cfg,
        path,
        output_dir,
        report,
        yes,
        run_tests,
        quiet,
        dry_run=dry_run,
        command="idiomatize",
    )


_PATTERNS = ("factory", "strategy", "observer", "singleton")


@app.command()
def pattern(
    pattern_name: str = typer.Argument("", help="factory|strategy|observer|singleton"),
    path: Path = typer.Argument(Path(".")),
    dry_run: bool = typer.Option(False, "--dry-run"),
    output_dir: Path | None = typer.Option(None, "--output-dir"),
    allow_fallback: bool = typer.Option(
        False, "--allow-fallback", help="Allow templates if the selected model fails"
    ),
    yes: bool = typer.Option(False, "--yes"),
    report: bool = typer.Option(False, "--report"),
    run_tests: bool = typer.Option(
        False, "--run-tests", help="Run target tests after edits; restore on failure"
    ),
    llm_api: str | None = typer.Option(None, "--llm-api", help="openai or anthropic"),
    llm_base_url: str | None = typer.Option(None, "--llm-base-url", help="API root including /v1"),
    model: str | None = typer.Option(None, "--model"),
    config: Path | None = typer.Option(None, "--config", "-c"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Hide progress, not results or errors"),
):
    """Apply or suggest a design pattern (factory|strategy|observer|singleton)."""
    if pattern_name and pattern_name.lower() not in _PATTERNS:
        typer.echo(
            f"Unknown pattern '{pattern_name}'. Choose from: {', '.join(_PATTERNS)}", err=True
        )
        raise typer.Exit(2)
    cfg = _get_cfg(config, model=model, llm_api=llm_api, llm_base_url=llm_base_url)
    root = _resolve_repo(path)
    with progress("Preparing pattern suggestions...", quiet=quiet):
        svc = _new_app(root, cfg)
        plan = _run(svc.pattern(pattern_name, str(path), allow_fallback=allow_fallback))
    _review_and_apply(
        svc,
        plan,
        cfg,
        path,
        output_dir,
        report,
        yes,
        run_tests,
        quiet,
        dry_run=dry_run,
        command="pattern",
    )


@app.command()
def check(
    path: Path = typer.Argument(Path(".")),
    fail_on: str | None = typer.Option(None, "--fail-on", help="none, info, warning or critical"),
    config: Path | None = typer.Option(None, "--config", "-c"),
    verbose: bool | None = typer.Option(None, "--verbose/--no-verbose", "-v"),
    report: bool = typer.Option(False, "--report", "-r"),
    output_dir: Path | None = typer.Option(None, "--output-dir"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Hide progress, not results or errors"),
):
    """Report naming, function-length, and cyclomatic-complexity issues."""
    cfg = _get_cfg(config, verbose, check_fail_on=fail_on)
    with progress("Preparing quality check...", quiet=quiet):
        svc = _new_app(_resolve_repo(path), cfg)
        result = _run(svc.check(str(path)))
    typer.echo(
        f"Issues: {result['total_issues']} "
        f"(critical={result['critical']}, warning={result['warning']}, info={result['info']})"
    )
    if result.get("suppressed_count"):
        typer.echo(f"Suppressed findings: {result['suppressed_count']} (not counted by the gate)")
    from reducio.quality_gate import evaluate_gate

    result.update(evaluate_gate(result, cfg.check_fail_on))
    typer.echo(
        f"Quality gate: {cfg.check_fail_on}; {'failed' if result['gate_failed'] else 'passed' if cfg.check_fail_on != 'none' else 'disabled'}"
    )
    if cfg.verbose:
        for i in result["issues"]:
            typer.echo(
                f"{i['severity']}  {i['issue_type']}  {i['file']}:{i['line']}  "
                f"{i['symbol']}  {i['message']}"
            )
            if i.get("suggestion"):
                typer.echo(f"  {i['suggestion']}")
    if report:
        with progress("Writing quality report...", quiet=quiet):
            try:
                p = Reporter(cfg, output_dir, target=path).generate_check(result)
            except (OSError, StorageError) as error:
                typer.echo(f"Report failed: {error}", err=True)
                raise typer.Exit(1) from None
        typer.echo(f"Quality report: {p}")
    if any(issue["issue_type"] == "parse_error" for issue in result["issues"]):
        typer.echo("Quality check incomplete: some Python files could not be parsed.", err=True)
        raise typer.Exit(1)

    if result["gate_failed"]:
        raise typer.Exit(1)


@app.command()
def apply(
    session_id: str = typer.Argument(..., help="Session ID from a prior command"),
    path: Path = typer.Argument(Path(".")),
    yes: bool = typer.Option(False, "--yes"),
    output_dir: Path | None = typer.Option(None, "--output-dir"),
    report: bool = typer.Option(False, "--report"),
    run_tests: bool = typer.Option(
        False, "--run-tests", help="Run target tests after edits; restore on failure"
    ),
    config: Path | None = typer.Option(None, "--config", "-c"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Hide progress, not results or errors"),
):
    """Apply a previously saved plan by session ID."""
    cfg = _get_cfg(config)
    root = Path(_resolve_repo(path))
    plan = _load_plan(root, session_id)
    if not plan:
        typer.echo(f"Session not found: {session_id}", err=True)
        raise typer.Exit(1)
    plan.diagnostics.extend(validate_plan(plan, root))
    svc = _new_app(str(root), cfg)
    _review_and_apply(svc, plan, cfg, path, output_dir, report, yes, run_tests, quiet)


@app.command("report")
def report_cmd(
    session_id: str = typer.Argument("", help="Session ID or empty for latest"),
    config: Path | None = typer.Option(None, "--config", "-c"),
    path: Path = typer.Option(Path("."), "--path", "-C", help="Repository path"),
    output_dir: Path | None = typer.Option(None, "--output-dir"),
):
    """Print a saved report (latest, or the given session ID)."""
    cfg = _get_cfg(config)
    try:
        text = Reporter(cfg, output_dir, target=_resolve_repo(path)).load_latest(session_id)
    except StorageError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from None
    except FileNotFoundError:
        typer.echo("No report found. Run a command with --report first.", err=True)
        raise typer.Exit(1) from None
    except OSError:
        typer.echo("Report could not be read.", err=True)
        raise typer.Exit(1) from None
    typer.echo(terminal_text(text))


sessions_app = typer.Typer(help="Manage refactoring sessions")
app.add_typer(sessions_app, name="sessions")


def _session_store(path: Path) -> SessionStore:
    try:
        return SessionStore(storage_dir=str(Path(_resolve_repo(path)) / ".reducio" / "sessions"))
    except StorageError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from None


def _load_plan(path: Path, session_id: str) -> RefactorPlan | None:
    try:
        validate_session_id(session_id)
        return _session_store(path).load_plan(session_id)
    except StorageError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from None


@sessions_app.command("list")
def sessions_list(path: Path = typer.Option(Path("."), "--path", "-C", help="Repository path")):
    """List saved refactoring sessions."""
    store = _session_store(path)
    items = store.list_sessions()
    if not items:
        typer.echo("No sessions in .reducio/sessions/")
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
    plan = _load_plan(path, session_id)
    if not plan:
        typer.echo("Not found", err=True)
        raise typer.Exit(1)
    _show_plan(plan)


@sessions_app.command("cleanup")
def sessions_cleanup(
    days: int = typer.Option(7, min=0, help="Delete sessions older than N days"),
    path: Path = typer.Option(Path("."), "--path", "-C", help="Repository path"),
):
    """Delete sessions older than N days."""
    n = _session_store(path).cleanup_old_sessions(days)
    typer.echo(f"Deleted {n} session(s)")


@app.command()
def version():
    """Show the reducio version."""
    typer.echo(f"reducio {__version__}")


def main():
    app()


if __name__ == "__main__":
    main()
