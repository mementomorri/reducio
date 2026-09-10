"""Markdown/JSON and offline HTML dashboards from the same measured result."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from html import escape
from pathlib import Path
from typing import Any

from reducto.models import AnalyzeResult, CompareResult, FunctionMetrics

Result = AnalyzeResult | CompareResult


class ReportFormat(StrEnum):
    MARKDOWN = "markdown"
    HTML = "html"
    JSON = "json"
    ALL = "all"


class ReportError(ValueError):
    pass


def _label(function: FunctionMetrics | None) -> str:
    if function is None:
        raise ReportError("Function record has neither a before nor an after measurement")
    return f"{function.file}:{function.line} · {function.qualified_name}"


def _matched(result: CompareResult):
    return [c for c in result.changes if c.before is not None and c.after is not None]


def _diagnostics(result: Result):
    diagnostics = result.diagnostics[:]
    if isinstance(result, CompareResult):
        diagnostics = result.before.diagnostics + result.after.diagnostics + diagnostics
    return diagnostics


def _summary(result: Result) -> list[tuple[str, str]]:
    if isinstance(result, CompareResult):
        counts = result.counts
        return [
            ("Changed Python files", str(len(result.files))),
            ("Matched functions", str(len(_matched(result)))),
            (
                "Improved / regressed / mixed",
                f"{counts['improved']} / {counts['regressed']} / {counts['mixed']}",
            ),
            ("Unchanged complexity", str(counts["unchanged"])),
            ("Added / removed functions", f"{counts['added']} / {counts['removed']}"),
            (
                "New / resolved hotspots",
                f"{counts['new_hotspots']} / {counts['resolved_hotspots']}",
            ),
        ]
    return [
        ("Total Files", str(result.total_files)),
        ("Total Symbols", str(result.total_symbols)),
        ("Measured functions", str(len(result.functions))),
        ("Complexity Hotspots", str(result.total_hotspots)),
        ("Physical source lines", str(sum(result.file_lines.values()))),
    ]


def _table(headers: list[str], rows: list[list[Any]], html: bool = False) -> str:
    if html:
        header = "".join(f'<th scope="col">{escape(h)}</th>' for h in headers)
        body = "".join(
            "<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>" for row in rows
        )
        return f'<div class="table-scroll"><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>'

    def cell(value):
        return escape(str(value)).replace("|", "&#124;").replace("\n", " ")

    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(cell(c) for c in row) + " |" for row in rows)
    return "\n".join(lines) + "\n"


def _rows(result: Result) -> tuple[list[str], list[list[Any]]]:
    if isinstance(result, AnalyzeResult):
        return ["Function", "Cyclomatic", "Cognitive", "Lines"], [
            [_label(f), f.cyclomatic_complexity, f.cognitive_complexity, f.lines_of_code]
            for f in sorted(
                result.functions, key=lambda f: (-f.cyclomatic_complexity, f.file, f.line)
            )
        ]
    rows = []
    ordered = sorted(
        result.changes,
        key=lambda c: (
            -abs(c.cyclomatic_delta or 0),
            -abs(c.cognitive_delta or 0),
            _label(c.after or c.before),
        ),
    )
    for change in ordered:
        before, after = change.before, change.after
        rows.append(
            [
                _label(after or before),
                change.status,
                f'{before.cyclomatic_complexity if before else "—"} → {after.cyclomatic_complexity if after else "—"}',
                f"{change.cyclomatic_delta:+d}" if change.cyclomatic_delta is not None else "—",
                f'{before.cognitive_complexity if before else "—"} → {after.cognitive_complexity if after else "—"}',
                f"{change.cognitive_delta:+d}" if change.cognitive_delta is not None else "—",
                f'{before.lines_of_code if before else "—"} → {after.lines_of_code if after else "—"}',
            ]
        )
    return [
        "Function",
        "Complexity change",
        "CC before → after",
        "Δ CC",
        "Cognitive before → after",
        "Δ cognitive",
        "Lines before → after",
    ], rows


def _context(result: Result) -> str:
    if isinstance(result, CompareResult):
        return (
            f"Changed files under {result.scope}. "
            f"{result.base_revision} → {result.head_revision}. "
            "Totals cover changed files only, not the entire repository. "
            "Improvements/regressions describe complexity, not functionality or correctness."
        )
    return f"Source overview · {result.scope}. Function-level metrics; class totals are not added to methods."


def _threshold(result: Result) -> int:
    return int(
        result.configuration.get("complexity_thresholds", {}).get("cyclomatic_complexity", 10)
    )


def markdown_report(result: Result) -> str:
    title = (
        "Revision Comparison" if isinstance(result, CompareResult) else "Baseline Analysis Report"
    )
    lines = [
        f"# reducto {title}",
        "",
        _context(result),
        "",
        f'Metrics version: {result.metrics_version} · Status: {"Complete" if result.complete else "INCOMPLETE"}',
        "",
        f"Hotspots have cyclomatic complexity ≥ {_threshold(result)}. Cognitive is the Reducto nesting-weighted score.",
        "",
        "## Summary",
        "",
        _table(["Metric", "Value"], [list(row) for row in _summary(result)]),
    ]
    if isinstance(result, AnalyzeResult):
        lines += [
            "## Complexity Hotspots",
            "",
            _table(
                ["File", "Line", "Symbol", "Cyclomatic", "Cognitive"],
                [
                    [h.file, h.line, h.symbol, h.cyclomatic_complexity, h.cognitive_complexity]
                    for h in result.hotspots[:20]
                ],
            ),
        ]
    headers, rows = _rows(result)
    lines += [
        "## Function measurements" if isinstance(result, AnalyzeResult) else "## Largest changes",
        "",
        _table(headers, rows[:20]),
        f"Showing up to 20 of {len(rows)} function records. HTML and JSON contain every record.",
        "",
    ]
    if isinstance(result, CompareResult):
        lines.extend(result.notes)
        if not result.files and result.complete:
            lines += ["No Python changes in the selected scope.", ""]
    if diagnostics := _diagnostics(result):
        lines += [
            "## Unavailable measurements",
            "",
            _table(
                ["File", "Line", "Revision", "Error"],
                [
                    [d.file, d.line or "—", d.revision or "working tree", d.message]
                    for d in diagnostics
                ],
            ),
        ]
    return "\n".join(lines) + "\n"


def _figures(result: Result) -> list[Any]:
    try:
        import plotly.graph_objects as go
    except ImportError as error:
        raise ReportError('HTML reports require: pip install "reducto[reports]"') from error

    figures = []
    if isinstance(result, AnalyzeResult):
        functions = result.functions
        distribution = go.Figure(
            go.Histogram(
                x=[f.cyclomatic_complexity for f in functions],
                xbins=dict(start=0.5, size=1),
                marker_color="#2563eb",
                name="Functions",
            )
        )
        distribution.update_layout(
            title="How widely is complexity distributed?",
            xaxis_title="Cyclomatic complexity",
            yaxis_title="Functions",
        )
        scatter = go.Figure(
            go.Scatter(
                x=[f.lines_of_code for f in functions],
                y=[f.cyclomatic_complexity for f in functions],
                text=[escape(_label(f)) for f in functions],
                mode="markers",
                marker=dict(
                    size=10,
                    color=[f.cognitive_complexity for f in functions],
                    colorscale="Blues",
                    colorbar=dict(title="Cognitive"),
                    line=dict(width=1, color="#1e3a8a"),
                ),
                hovertemplate="%{text}<br>Lines: %{x}<br>CC: %{y}<br>Cognitive: %{marker.color}<extra></extra>",
            )
        )
        scatter.add_hline(y=_threshold(result), line_dash="dash", line_color="#d97706")
        scatter.update_layout(
            title="Where are the long, complex functions?",
            xaxis_title="Function length (physical lines)",
            yaxis_title="Cyclomatic complexity",
        )
        top = sorted(functions, key=lambda f: (-f.cyclomatic_complexity, f.file, f.line))[:20]
        bars = go.Figure(
            go.Bar(
                x=[f.cyclomatic_complexity for f in top],
                y=[escape(_label(f)) for f in top],
                orientation="h",
                marker_color="#2563eb",
            )
        )
        bars.update_layout(
            title="Highest-complexity functions · top 20",
            xaxis_title="Cyclomatic complexity",
            yaxis=dict(autorange="reversed"),
        )
        figures = [distribution, scatter, bars]
    else:
        matched = _matched(result)
        ranked = sorted(
            matched,
            key=lambda c: (
                -abs(c.cyclomatic_delta or 0),
                -abs(c.cognitive_delta or 0),
                _label(c.after),
            ),
        )[:20]
        names = [escape(_label(c.after)) for c in ranked]
        for field, title in [
            ("cyclomatic_complexity", "Cyclomatic"),
            ("cognitive_complexity", "Cognitive"),
        ]:
            bars = go.Figure()
            for side, color in [("before", "#94a3b8"), ("after", "#2563eb")]:
                bars.add_trace(
                    go.Bar(
                        name=side.title(),
                        y=names,
                        x=[getattr(getattr(c, side), field) for c in ranked],
                        orientation="h",
                        marker_color=color,
                    )
                )
            bars.update_layout(
                title=f"{title} before / after · matched functions, top 20 changes",
                barmode="group",
                xaxis_title=title,
                yaxis=dict(autorange="reversed"),
            )
            figures.append(bars)
        delta = go.Figure(
            go.Bar(
                x=[c.cyclomatic_delta for c in ranked],
                y=names,
                text=[f"{c.cyclomatic_delta:+d}" for c in ranked],
                textposition="auto",
                orientation="h",
                marker_color=[
                    (
                        "#0f766e"
                        if c.cyclomatic_delta < 0
                        else "#c2410c" if c.cyclomatic_delta > 0 else "#64748b"
                    )
                    for c in ranked
                ],
            )
        )
        delta.add_vline(x=0, line_color="#0f172a")
        delta.update_layout(
            title="Change in cyclomatic complexity · lower is simpler",
            xaxis_title="After − before",
            yaxis=dict(autorange="reversed"),
        )
        distribution = go.Figure()
        for side, color in [("before", "#94a3b8"), ("after", "#2563eb")]:
            distribution.add_trace(
                go.Histogram(
                    x=[getattr(c, side).cyclomatic_complexity for c in matched],
                    name=side.title(),
                    marker_color=color,
                    opacity=0.7,
                    xbins=dict(start=0.5, size=1),
                )
            )
        distribution.update_layout(
            title="Same matched functions · complexity distribution",
            barmode="overlay",
            xaxis_title="Cyclomatic complexity",
            yaxis_title="Functions",
        )
        figures += [delta, distribution]
    for figure in figures:
        figure.update_layout(
            template="plotly_white",
            font=dict(family="Arial, sans-serif", color="#1e293b"),
            margin=dict(l=30, r=30, t=75, b=55),
            height=480,
        )
        figure.update_yaxes(automargin=True)
    return figures


def html_report(result: Result) -> str:
    figures = _figures(result)
    charts = "".join(
        '<section class="chart">'
        + figure.to_html(
            full_html=False,
            include_plotlyjs=(index == 0),
            include_mathjax=False,
            div_id=f"chart-{index}",
            config={"responsive": True, "displaylogo": False},
        )
        + "</section>"
        for index, figure in enumerate(figures)
    )
    title = "Change impact" if isinstance(result, CompareResult) else "Code overview"
    cards = "".join(
        f'<div class="card"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'
        for label, value in _summary(result)
    )
    headers, rows = _rows(result)
    diagnostics = _diagnostics(result)
    errors = (
        (
            "<section><h2>Unavailable measurements</h2>"
            + _table(
                ["File", "Line", "Revision", "Error"],
                [
                    [d.file, d.line or "—", d.revision or "working tree", d.message]
                    for d in diagnostics
                ],
                html=True,
            )
            + "</section>"
        )
        if diagnostics
        else ""
    )
    notes = (
        "".join(f"<p>{escape(note)}</p>" for note in result.notes)
        if isinstance(result, CompareResult)
        else ""
    )
    empty = (
        '<p class="notice">No comparable function measurements in this scope.</p>'
        if not rows
        else ""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>reducto · {title}</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f1f5f9;color:#1e293b;font:15px/1.6 system-ui,sans-serif}}
header{{background:#0f172a;color:#f8fafc;padding:38px max(24px,calc((100vw - 1240px)/2))}}
header p{{color:#cbd5e1;overflow-wrap:anywhere;max-width:1100px}}h1{{font-size:36px;margin:8px 0}}h2{{font-size:21px}}
.eyebrow{{color:#67e8f9;letter-spacing:.15em;text-transform:uppercase;font-size:12px}}
main{{max-width:1290px;padding:28px 24px;margin:auto}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px}}
.card,section{{background:white;border:1px solid #e2e8f0;border-radius:12px;padding:22px;margin-bottom:20px}}
.card span{{display:block;color:#64748b;font-size:13px}}.card strong{{display:block;font-size:28px;margin-top:8px}}
.chart{{padding:12px;overflow:hidden}}.table-scroll{{overflow:auto;max-height:650px}}table{{width:100%;border-collapse:collapse;font-size:13px}}
td,th{{text-align:left;padding:11px 14px;border-bottom:1px solid #e2e8f0;white-space:nowrap}}
th{{background:#f8fafc;position:sticky;top:0}}tr:nth-child(even){{background:#f8fafc}}
.notice{{padding:14px;background:#fff7ed;border-left:4px solid #c2410c}}code{{overflow-wrap:anywhere}}
details{{margin-top:18px}}footer{{color:#64748b;font-size:13px;margin:22px 0}}
</style></head><body><header><div class="eyebrow">reducto / metrics v{result.metrics_version}</div>
<h1>{title}</h1><p>{escape(_context(result))}</p>
<p>Status: <strong>{'Complete' if result.complete else 'INCOMPLETE — see unavailable measurements'}</strong></p></header>
<main><div class="cards">{cards}</div>{errors}{empty}{charts}
<section><h2>All function measurements</h2>{notes}{_table(headers, rows, html=True)}</section>
<section><h2>Reading these results</h2><p>Lower complexity can make code easier to understand, but does not prove correctness.
Added and removed functions are separate from changes to existing functions. A mixed result means one complexity metric rose while the other fell.
Physical line counts include comments and blank lines; fewer lines alone are not an improvement verdict.</p>
<p>Cyclomatic counts syntax decisions, starting at 1 per function. Cognitive is Reducto's nesting-weighted score, starting at 0;
it does not claim Sonar compatibility. Hotspots have cyclomatic complexity ≥ {_threshold(result)}.
Nested functions are measured independently. Module/class-body control flow is outside the function-level scores.</p>
<details><summary>Measurement configuration</summary><pre>{escape(str(result.configuration))}</pre></details></section>
<footer>Self-contained report · works offline · complete data also available with --format json or all.</footer></main></body></html>"""


def write_reports(
    result: Result, output_dir: str | Path, format: ReportFormat = ReportFormat.MARKDOWN
) -> list[Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    kind = "compare" if isinstance(result, CompareResult) else "baseline"
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    stem = f"reducto-{kind}-{stamp}"
    paths = []
    formats = (
        [ReportFormat.MARKDOWN, ReportFormat.JSON, ReportFormat.HTML]
        if format == ReportFormat.ALL
        else [format]
    )
    for selected in formats:
        if selected == ReportFormat.MARKDOWN:
            suffix, content = "md", markdown_report(result)
        elif selected == ReportFormat.JSON:
            suffix, content = "json", result.model_dump_json(indent=2)
        else:
            suffix, content = "html", html_report(result)
        path = output / f"{stem}.{suffix}"
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    return paths
