"""Read-only Git revision comparison; target Python is parsed, never imported."""

from __future__ import annotations

import io
import os
import subprocess
from pathlib import Path, PurePosixPath

from reducio.analysis import analysis_configuration, analyze_files, match_functions
from reducio.models import (
    AnalysisDiagnostic,
    AppConfig,
    CompareResult,
)
from reducio.progress import status as report_status
from reducio.repo import _read_one, included, source_file


class CompareError(ValueError):
    pass


def _git(root: Path, *args: str, input: bytes | None = None) -> bytes:
    try:
        process = subprocess.run(
            ["git", "--literal-pathspecs", "-C", str(root), *args],
            capture_output=True,
            timeout=60,
            input=input,
            # Even status/diff may refresh Git's index unless optional locks are disabled.
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CompareError(str(error)) from error
    if process.returncode:
        raise CompareError(process.stderr.decode("utf-8", errors="replace").strip())
    return process.stdout


def worktree_clean(path: str) -> bool:
    """True unless a Git work tree containing `path` has changes; non-repositories are clean."""
    try:
        return not _git(Path(path), "status", "--porcelain", "--untracked-files=normal").strip()
    except CompareError:
        return True


def tree_entries(root: Path, revision: str) -> dict[str, tuple[str, str]]:
    entries = {}
    for record in _git(root, "ls-tree", "-r", "-z", revision).split(b"\0"):
        if record:
            metadata, name = record.split(b"\t", 1)
            mode, _, oid = metadata.decode("ascii").split()
            entries[name.decode("utf-8", "surrogateescape")] = (mode, oid)
    return entries


def _read_blobs(root: Path, identifiers: list[str]):
    # Send only ls-tree object IDs, never filenames, through the batch protocol.
    for start in range(0, len(identifiers), 128):
        batch = identifiers[start : start + 128]
        data = io.BytesIO(
            _git(root, "cat-file", "--batch", input="".join(f"{oid}\n" for oid in batch).encode())
        )
        for oid in batch:
            header = data.readline().decode("ascii").split()
            if len(header) != 3 or header[:2] != [oid, "blob"]:
                raise CompareError("Cannot read a historical Git blob")
            size = int(header[2])
            content = data.read(size)
            if len(content) != size or data.read(1) != b"\n":
                raise CompareError("Truncated historical Git blob")
            yield oid, content


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
            *([head] if head else []),
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
    files, diagnostics, blobs = [], [], {}
    entries = tree_entries(root, revision) if paths else {}
    for path in sorted(set(paths)):
        mode, oid = entries.get(path, ("", ""))
        if mode in ("100644", "100755"):
            blobs[path] = oid
        else:
            message = "Source is not a regular Git blob (symlinks are not followed)"
            diagnostics.append(
                AnalysisDiagnostic(file=path, message=message if mode else "Missing at revision")
            )
    data = dict(_read_blobs(root, sorted(set(blobs.values()))))
    for path, oid in blobs.items():
        try:
            files.append(source_file(path, data[oid]))
        except (UnicodeError, LookupError, SyntaxError) as error:
            diagnostics.append(AnalysisDiagnostic(file=path, message=str(error)))
    result = analyze_files(files, cfg, scope)
    result.diagnostics.extend(diagnostics)
    result.total_files = len(set(paths))
    for diagnostic in result.diagnostics:
        diagnostic.revision = revision
    return result


def compare_revisions(
    path: str,
    base: str | None = None,
    head: str = "HEAD",
    cfg: AppConfig | None = None,
    *,
    against: str | None = None,
    worktree: bool = False,
) -> CompareResult:
    report_status("Resolving Git revisions...")
    cfg = cfg or AppConfig()
    if bool(base) == bool(against) or (against or worktree) and head != "HEAD":
        raise ValueError(
            "Choose --base or --against; --against/--worktree cannot use a custom --head"
        )
    target = Path(path).resolve()
    root = Path(_git(target, "rev-parse", "--show-toplevel").decode().strip())
    scope = target.relative_to(root).as_posix()
    if against:
        against_sha = (
            _git(root, "rev-parse", "--verify", "--end-of-options", f"{against}^{{commit}}")
            .decode()
            .strip()
        )
        base = _git(root, "merge-base", against_sha, "HEAD").decode().strip()
    base_sha, head_sha = (
        _git(root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
        .decode()
        .strip()
        for ref in (base, head)
    )
    report_status("Finding changed Python files...")
    files = _changed_files(root, base_sha, "" if worktree else head_sha, scope, cfg)
    if worktree:
        known = {f["after"] for f in files}
        deleted = {f["before"]: f for f in files if f["after"] is None}
        for name in (
            _git(root, "ls-files", "--others", "--exclude-standard", "-z")
            .decode("utf-8", "surrogateescape")
            .split("\0")
        ):
            if name and name not in known and _included(name, scope, cfg):
                if name in deleted:
                    deleted[name].update(status="M", after=name)
                else:
                    files.append({"status": "A", "before": None, "after": name})
        files.sort(key=lambda f: f["after"] or f["before"])
    report_status(f"Reading base snapshot ({len(files)} changed files)...")
    before = _snapshot(root, base_sha, [f["before"] for f in files if f["before"]], cfg, scope)
    report_status(f"Reading head snapshot ({len(files)} changed files)...")
    paths = [f["after"] for f in files if f["after"]]
    after = (
        analyze_files([_read_one(root, root / p) for p in paths], cfg, scope)
        if worktree
        else _snapshot(root, head_sha, paths, cfg, scope)
    )
    report_status("Matching functions and comparing complexity...")
    result = CompareResult(
        scope=scope,
        base_revision=base_sha,
        head_revision=head_sha,
        files=files,
        configuration=analysis_configuration(cfg),
        before=before,
        after=after,
        head_source="worktree" if worktree else "commit",
        gate_threshold=cfg.compare_fail_on,
    )
    result.changes, result.notes = match_functions(
        before,
        after,
        cfg.complexity_thresholds.cyclomatic_complexity,
        [(f["before"], f["after"]) for f in files],
    )
    if worktree:
        result.notes.append(
            "Head source: WORKTREE; head_revision is the HEAD anchor, not the measured working-file contents. Untracked nonignored Python files are included."
        )
    from reducio.quality_gate import comparison_failed

    result.gate_failed = comparison_failed(result)
    return result
