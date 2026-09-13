"""Read-only Git revision comparison; target Python is parsed, never imported."""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

from reducio.analysis import analysis_configuration, analyze_files, match_functions
from reducio.models import (
    AnalysisDiagnostic,
    AppConfig,
    CompareResult,
)
from reducio.progress import status as report_status
from reducio.repo import included, source_file


class CompareError(ValueError):
    pass


def _git(root: Path, *args: str) -> bytes:
    try:
        process = subprocess.run(
            ["git", "--literal-pathspecs", "-C", str(root), *args],
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CompareError(str(error)) from error
    if process.returncode:
        raise CompareError(process.stderr.decode("utf-8", errors="replace").strip())
    return process.stdout


def _included(path: str | None, scope: str, cfg: AppConfig) -> bool:
    if path is None:
        return False
    candidate = PurePosixPath(path)
    if not candidate.is_relative_to(scope):
        return False
    relative = candidate.relative_to(scope)
    return included(str(relative), cfg.exclude_patterns, cfg.include_patterns)


def _changed_files(root: Path, base: str, head: str, scope: str, cfg: AppConfig) -> list[dict]:
    tokens = iter(
        _git(
            root,
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--name-status",
            "-z",
            "--find-renames",
            base,
            head,
            "--",
        )
        .decode("utf-8", errors="surrogateescape")
        .rstrip("\0")
        .split("\0")
    )
    changes = []
    for status in tokens:
        if not status:
            continue
        first = next(tokens)
        old, new = (first, next(tokens)) if status.startswith("R") else (first, first)
        old_path = None if status == "A" or not _included(old, scope, cfg) else old
        new_path = None if status == "D" or not _included(new, scope, cfg) else new
        if old_path is not None or new_path is not None:
            changes.append({"status": status, "before": old_path, "after": new_path})
    return changes


def _snapshot(root: Path, revision: str, paths: list[str], cfg: AppConfig, scope: str):
    files, diagnostics = [], []
    for path in sorted(set(paths)):
        try:
            entry = _git(root, "ls-tree", "-z", revision, "--", path)
            if not entry.startswith((b"100644 ", b"100755 ")):
                raise CompareError("Source is not a regular Git blob (symlinks are not followed)")
            data = _git(root, "cat-file", "blob", f"{revision}:{path}")
            files.append(source_file(path, data))
        except (CompareError, UnicodeError, LookupError, SyntaxError) as error:
            diagnostics.append(AnalysisDiagnostic(file=path, message=str(error), revision=revision))
    result = analyze_files(files, cfg, scope)
    result.diagnostics.extend(diagnostics)
    result.total_files = len(set(paths))
    for diagnostic in result.diagnostics:
        diagnostic.revision = revision
    return result


def compare_revisions(
    path: str, base: str, head: str = "HEAD", cfg: AppConfig | None = None
) -> CompareResult:
    report_status("Resolving Git revisions...")
    cfg = cfg or AppConfig()
    target = Path(path).resolve()
    root = Path(_git(target, "rev-parse", "--show-toplevel").decode().strip())
    scope = target.relative_to(root).as_posix()
    base_sha, head_sha = (
        _git(root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
        .decode()
        .strip()
        for ref in (base, head)
    )
    report_status("Finding changed Python files...")
    files = _changed_files(root, base_sha, head_sha, scope, cfg)
    report_status(f"Reading base snapshot ({len(files)} changed files)...")
    before = _snapshot(root, base_sha, [f["before"] for f in files if f["before"]], cfg, scope)
    report_status(f"Reading head snapshot ({len(files)} changed files)...")
    after = _snapshot(root, head_sha, [f["after"] for f in files if f["after"]], cfg, scope)
    report_status("Matching functions and comparing complexity...")
    result = CompareResult(
        scope=scope,
        base_revision=base_sha,
        head_revision=head_sha,
        files=files,
        configuration=analysis_configuration(cfg),
        before=before,
        after=after,
    )
    result.changes, result.notes = match_functions(
        before,
        after,
        cfg.complexity_thresholds.cyclomatic_complexity,
        [(f["before"], f["after"]) for f in files],
    )
    return result
