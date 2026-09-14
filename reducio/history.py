"""Rebuild comparable history from Git blobs, without checking out or executing code."""

from __future__ import annotations

import io
import math
from pathlib import Path, PurePosixPath
from statistics import median

from reducio import __version__
from reducio.analysis import analysis_configuration, analyze_files, match_functions
from reducio.compare import CompareError, _git
from reducio.models import (
    AnalysisDiagnostic,
    AnalyzeResult,
    AppConfig,
    HistoryResult,
    HistorySnapshot,
)
from reducio.progress import status
from reducio.repo import included, source_file


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


def _scope(value: str) -> str:
    path = PurePosixPath(value)
    if not value.strip() or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("History path aliases must be repository-relative directories")
    return str(path)


def history_revisions(path: str, ref: str = "HEAD", cfg: AppConfig | None = None) -> HistoryResult:
    cfg = cfg or AppConfig()
    target = Path(path).resolve()
    root = Path(_git(target, "rev-parse", "--show-toplevel").decode().strip())
    scope = target.relative_to(root).as_posix()
    aliases = list(dict.fromkeys([scope, *map(_scope, cfg.history_path_aliases)]))
    revision = (
        _git(root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
        .decode()
        .strip()
    )
    if _git(root, "rev-parse", "--is-shallow-repository").strip() == b"true":
        raise CompareError(
            "History needs full Git history; use fetch-depth: 0 or git fetch --unshallow"
        )
    revisions = (
        _git(root, "rev-list", "--first-parent", f"--max-count={cfg.history_limit}", revision)
        .decode()
        .splitlines()[::-1]
    )
    result = HistoryResult(
        tool_version=__version__,
        scope=scope,
        ref_revision=revision,
        limit=cfg.history_limit,
        configuration=analysis_configuration(cfg)
        | {"history_path_aliases": cfg.history_path_aliases},
    )
    cache: dict[str, AnalyzeResult] = {}
    for index, sha in enumerate(revisions):
        status(f"Reading history {index + 1}/{len(revisions)}: {sha[:10]}...")
        entries = tree_entries(root, sha)
        actual = next(
            (
                alias
                for alias in aliases
                if alias == "." or any(p.startswith(f"{alias}/") for p in entries)
            ),
            None,
        )
        measurement = AnalyzeResult(
            total_files=0,
            total_symbols=0,
            hotspots=[],
            scope=scope,
            configuration=analysis_configuration(cfg),
        )
        selected = {}
        if actual is None:
            measurement.diagnostics.append(
                AnalysisDiagnostic(
                    file=scope,
                    revision=sha,
                    message="Source scope absent at this revision (including configured aliases)",
                )
            )
        else:
            selected = {
                p: entry
                for p, entry in entries.items()
                if PurePosixPath(p).is_relative_to(actual)
                and included(
                    str(PurePosixPath(p).relative_to(actual)),
                    cfg.exclude_patterns,
                    cfg.include_patterns,
                )
            }
        missing = sorted(
            {
                oid
                for mode, oid in selected.values()
                if mode in ("100644", "100755") and oid not in cache
            }
        )
        for oid, data in _read_blobs(root, missing):
            try:
                cached = analyze_files([source_file("source.py", data)], cfg, announce=False)
            except UnicodeError, LookupError, SyntaxError:
                cached = AnalyzeResult(
                    total_files=1,
                    total_symbols=0,
                    hotspots=[],
                    diagnostics=[
                        AnalysisDiagnostic(
                            file="source.py", message="Cannot decode historical Python source"
                        )
                    ],
                )
            cache[oid] = cached
        for name, (mode, oid) in sorted(selected.items()):
            canonical = str(PurePosixPath(scope) / PurePosixPath(name).relative_to(actual or scope))
            measurement.total_files += 1
            if mode not in ("100644", "100755"):
                measurement.diagnostics.append(
                    AnalysisDiagnostic(
                        file=canonical,
                        revision=sha,
                        message="Historical source is not a regular Git blob",
                    )
                )
                continue
            cached = cache[oid]
            if cached.file_lines:
                measurement.file_lines[canonical] = cached.file_lines["source.py"]
            for attribute in ("functions", "symbols", "hotspots", "diagnostics"):
                for record in getattr(cached, attribute):
                    updates = {"file": canonical}
                    if attribute == "diagnostics":
                        updates["revision"] = sha
                    getattr(measurement, attribute).append(record.model_copy(update=updates))
        measurement.total_symbols = len(measurement.symbols)
        measurement.hotspots.sort(key=lambda h: (-h.cyclomatic_complexity, h.file, h.line))
        date, _, subject = (
            _git(root, "show", "-s", "--format=%cI%n%s", sha)
            .decode("utf-8", "replace")
            .strip()
            .partition("\n")
        )
        snapshot = HistorySnapshot(
            revision=sha,
            committed_at=date,
            subject=subject,
            actual_scope=actual,
            measurement=measurement,
        )
        if result.snapshots:
            previous = result.snapshots[-1]
            if actual != previous.actual_scope:
                snapshot.notes.append(
                    f"Source scope changed: {previous.actual_scope or 'absent'} → {actual or 'absent'}"
                )
            if previous.measurement.complete and measurement.complete:
                snapshot.comparison_available = True
                snapshot.changes, notes = match_functions(
                    previous.measurement,
                    measurement,
                    cfg.complexity_thresholds.cyclomatic_complexity,
                )
                snapshot.notes.extend(notes)
            else:
                snapshot.notes.append("Previous-commit deltas unavailable across a history gap")
        result.snapshots.append(snapshot)
    result.unique_blobs_analyzed = len(cache)
    return result


def snapshot_metrics(snapshot: HistorySnapshot) -> dict:
    measurement = snapshot.measurement
    if not measurement.complete:
        return {}
    functions = measurement.functions
    metrics = {
        "loc": sum(measurement.file_lines.values()),
        "functions": len(functions),
        "hotspots": len(measurement.hotspots),
        "hotspot_share": 100 * len(measurement.hotspots) / len(functions) if functions else None,
    }
    for attribute, label in (
        ("cyclomatic_complexity", "cc"),
        ("cognitive_complexity", "cognitive"),
    ):
        values = sorted(getattr(f, attribute) for f in functions)
        metrics[f"median_{label}"] = median(values) if values else None
        metrics[f"p95_{label}"] = values[math.ceil(len(values) * 0.95) - 1] if values else None
    # None distinguishes no measurable predecessor from a genuine zero change.
    available = snapshot.comparison_available
    metrics["new_hotspots"] = sum(c.new_hotspot for c in snapshot.changes) if available else None
    metrics["resolved_hotspots"] = (
        sum(c.resolved_hotspot for c in snapshot.changes) if available else None
    )
    return metrics
