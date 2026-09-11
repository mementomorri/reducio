"""Read-only Git revision comparison; target Python is parsed, never imported."""

from __future__ import annotations

import io
import subprocess
import tokenize
from collections import defaultdict
from pathlib import Path, PurePosixPath

from reducio.analysis import analysis_configuration, analyze_files
from reducio.models import (
    AnalysisDiagnostic,
    AppConfig,
    CompareResult,
    FileInfo,
    FunctionComparison,
    FunctionMetrics,
)
from reducio.progress import status as report_status
from reducio.repo import _should_exclude_dir, _should_exclude_file, _should_include


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
    return (
        relative.suffix == ".py"
        and not _should_exclude_file(relative.name)
        and _should_include(str(relative), cfg.include_patterns)
        and not any(
            _should_exclude_dir(p.name, str(p), cfg.exclude_patterns)
            for p in relative.parents
            if str(p) != "."
        )
    )


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
            encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
            files.append(FileInfo(path=path, content=data.decode(encoding)))
        except (CompareError, UnicodeError, LookupError, SyntaxError) as error:
            diagnostics.append(AnalysisDiagnostic(file=path, message=str(error), revision=revision))
    result = analyze_files(files, cfg, scope)
    result.diagnostics.extend(diagnostics)
    result.total_files = len(set(paths))
    for diagnostic in result.diagnostics:
        diagnostic.revision = revision
    return result


def _comparison(before: FunctionMetrics | None, after: FunctionMetrics | None, threshold: int):
    was_hot = before is not None and before.cyclomatic_complexity >= threshold
    now_hot = after is not None and after.cyclomatic_complexity >= threshold
    values: dict = dict(
        before=before,
        after=after,
        new_hotspot=now_hot and not was_hot,
        resolved_hotspot=was_hot and not now_hot,
    )
    if before is None or after is None:
        return FunctionComparison(status="added" if before is None else "removed", **values)
    cc = after.cyclomatic_complexity - before.cyclomatic_complexity
    cognitive = after.cognitive_complexity - before.cognitive_complexity
    up, down = max(cc, cognitive) > 0, min(cc, cognitive) < 0
    status = "mixed" if up and down else "regressed" if up else "improved" if down else "unchanged"
    return FunctionComparison(
        status=status,
        cyclomatic_delta=cc,
        cognitive_delta=cognitive,
        lines_delta=after.lines_of_code - before.lines_of_code,
        **values,
    )


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
    grouped = []
    for snapshot in (before, after):
        index: dict[str, dict[str, list[FunctionMetrics]]] = defaultdict(lambda: defaultdict(list))
        for function in snapshot.functions:
            index[function.file][function.qualified_name].append(function)
        grouped.append(index)
    bad_before = {d.file for d in before.diagnostics}
    bad_after = {d.file for d in after.diagnostics}
    threshold = cfg.complexity_thresholds.cyclomatic_complexity
    for file in files:
        if file["before"] in bad_before or file["after"] in bad_after:
            continue  # unavailable is not an addition, removal, or improvement
        old, new = grouped[0].get(file["before"], {}), grouped[1].get(file["after"], {})
        for name in sorted(old.keys() | new.keys()):
            left, right = old.get(name, []), new.get(name, [])
            if len(left) == len(right) == 1:
                result.changes.append(_comparison(left[0], right[0], threshold))
            else:
                if len(left) > 1 or len(right) > 1:
                    result.notes.append(
                        f"Ambiguous definition {file['after'] or file['before']}:{name}; shown unmatched"
                    )
                result.changes.extend(_comparison(f, None, threshold) for f in left)
                result.changes.extend(_comparison(None, f, threshold) for f in right)
    return result
