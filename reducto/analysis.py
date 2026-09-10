"""Pure source analysis shared by workspace scans and revision comparisons."""

from __future__ import annotations

import ast
from collections.abc import Iterable

from reducto.metrics import functions_from_tree
from reducto.models import (
    AnalysisDiagnostic,
    AnalyzeResult,
    AppConfig,
    ComplexityHotspot,
    FileInfo,
    Symbol,
)


def analysis_configuration(cfg: AppConfig) -> dict:
    # Persist only inputs to measurement, never model/provider credentials.
    return {key: getattr(cfg, key) for key in ("include_patterns", "exclude_patterns")} | {
        "complexity_thresholds": cfg.complexity_thresholds.model_dump(),
    }


def analyze_files(files: Iterable[FileInfo], cfg: AppConfig, scope: str = ".") -> AnalyzeResult:
    result = AnalyzeResult(
        total_files=0,
        total_symbols=0,
        hotspots=[],
        scope=scope,
        configuration=analysis_configuration(cfg),
    )
    for file in sorted(files, key=lambda f: f.path):
        if not file.path.endswith(".py"):
            continue
        result.total_files += 1
        result.file_lines[file.path] = len(file.content.splitlines())
        try:
            tree = ast.parse(file.content, filename=file.path)
        except (SyntaxError, ValueError) as error:
            result.diagnostics.append(
                AnalysisDiagnostic(
                    file=file.path,
                    line=getattr(error, "lineno", None),
                    message=getattr(error, "msg", str(error)),
                )
            )
            continue
        functions = functions_from_tree(tree, file.path)
        result.functions.extend(functions)
        result.symbols.extend(
            Symbol(
                name=f.name,
                type=f.kind,
                file=f.file,
                start_line=f.line,
                end_line=f.end_line,
            )
            for f in functions
        )
        result.symbols.extend(
            Symbol(
                name=n.name,
                type="class",
                file=file.path,
                start_line=n.lineno,
                end_line=n.end_lineno or n.lineno,
            )
            for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef)
        )
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
