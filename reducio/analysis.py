"""Pure source analysis shared by workspace scans and revision comparisons."""

from __future__ import annotations

from collections.abc import Iterable

from reducio.metrics import functions_from_tree
from reducio.models import (
    AnalysisDiagnostic,
    AnalyzeResult,
    AppConfig,
    ComplexityHotspot,
    ComplexityMetrics,
    FileInfo,
    FunctionComparison,
    FunctionMetrics,
)
from reducio.parse import symbols_from_tree
from reducio.progress import status


def analysis_configuration(cfg: AppConfig) -> dict:
    # Persist only inputs to measurement, never model/provider credentials.
    return {key: getattr(cfg, key) for key in ("include_patterns", "exclude_patterns")} | {
        "complexity_thresholds": cfg.complexity_thresholds.model_dump(),
    }


def analyze_files(files: Iterable[FileInfo], cfg: AppConfig, scope: str = ".") -> AnalyzeResult:
    status("Analyzing Python functions and measuring complexity...")
    result = AnalyzeResult(
        total_files=0,
        total_symbols=0,
        hotspots=[],
        scope=scope,
        configuration=analysis_configuration(cfg),
    )
    for file in sorted(files, key=lambda f: f.path):
        if not file.error and not file.path.lower().endswith(".py"):
            continue
        result.total_files += 1
        try:
            tree = file.tree
        except (SyntaxError, ValueError) as error:
            result.diagnostics.append(
                AnalysisDiagnostic(
                    file=file.path,
                    line=getattr(error, "lineno", None),
                    message=getattr(error, "msg", str(error)),
                )
            )
            continue
        result.file_lines[file.path] = len(file.content.splitlines())
        functions = functions_from_tree(tree, file.path)
        result.functions.extend(functions)
        result.symbols.extend(symbols_from_tree(tree, file.path, functions))
        result.hotspots.extend(
            ComplexityHotspot(
                file=f.file,
                line=f.line,
                symbol=f.qualified_name,
                cyclomatic_complexity=f.cyclomatic_complexity,
                cognitive_complexity=f.cognitive_complexity,
            )
            for f in functions
            if f.cyclomatic_complexity >= cfg.complexity_thresholds.cyclomatic_complexity
        )
    result.total_symbols = len(result.symbols)
    result.hotspots.sort(key=lambda h: (-h.cyclomatic_complexity, h.file, h.line))
    return result


def totals(measurement: AnalyzeResult | None) -> ComplexityMetrics | None:
    if measurement is None or not measurement.complete:
        return None
    return ComplexityMetrics(
        lines_of_code=sum(measurement.file_lines.values()),
        cyclomatic_complexity=sum(f.cyclomatic_complexity for f in measurement.functions),
        cognitive_complexity=sum(f.cognitive_complexity for f in measurement.functions),
    )


def comparison(before: FunctionMetrics | None, after: FunctionMetrics | None, threshold: int):
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


def match_functions(before: AnalyzeResult, after: AnalyzeResult, threshold: int, pairs=None):
    """Match unambiguous qualified names/kinds, excluding unavailable files."""
    from collections import defaultdict

    indexes = []
    for snapshot in (before, after):
        index: dict[str, dict[tuple[str, str], list[FunctionMetrics]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for function in snapshot.functions:
            index[function.file][(function.qualified_name, function.kind)].append(function)
        indexes.append(index)
    pairs = (
        pairs
        if pairs is not None
        else [(p, p) for p in sorted(before.file_lines.keys() | after.file_lines.keys())]
    )
    bad = [{d.file for d in s.diagnostics} for s in (before, after)]
    changes, notes = [], []
    for old_path, new_path in pairs:
        if old_path in bad[0] or new_path in bad[1]:
            continue
        old, new = indexes[0].get(old_path, {}), indexes[1].get(new_path, {})
        for name in sorted(old.keys() | new.keys()):
            left, right = old.get(name, []), new.get(name, [])
            if len(left) == len(right) == 1:
                changes.append(comparison(left[0], right[0], threshold))
            else:
                if len(left) > 1 or len(right) > 1:
                    notes.append(
                        f"Ambiguous definition {new_path or old_path}:{name[0]}; shown unmatched"
                    )
                changes.extend(comparison(f, None, threshold) for f in left)
                changes.extend(comparison(None, f, threshold) for f in right)
    return changes, notes
