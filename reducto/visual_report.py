"""Markdown/JSON and offline HTML dashboards from the same measured result."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from html import escape
from pathlib import Path
from typing import Any

from reducto.models import AnalyzeResult, CompareResult, FunctionMetrics

Result = AnalyzeResult | CompareResult

# Match docs/index.html without external fonts/assets: reports remain offline.
_REPORT_STYLE = """
:root{color-scheme:dark;--bg-void:#0a0a12;--bg-deep:#12101f;--bg-night:#1a1530;
--gold:#d4a853;--gold-light:#f0d78c;--purple-glow:#8b5cf6;--text-light:#f0e6d3;
--text-muted:#a89ec9;--border-magic:rgba(139,92,246,.3)}
*{box-sizing:border-box}body{margin:0;background:var(--bg-void);color:var(--text-light);
font:17px/1.7 'Crimson Pro',Georgia,serif}
a{color:var(--gold);text-decoration:none}a:hover{color:var(--gold-light)}
a:focus-visible,summary:focus-visible{outline:2px solid var(--gold);outline-offset:5px}
header{border-bottom:1px solid var(--border-magic);padding:24px max(24px,calc((100vw - 1240px)/2)) 40px;
background:radial-gradient(ellipse at 75% 0,rgba(139,92,246,.2),transparent 65%),var(--bg-void)}
.navigation{display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap;margin-bottom:38px}
.brand{font-family:'Cinzel',Georgia,serif;font-size:26px;font-weight:bold;letter-spacing:.1em}
.brand span{color:var(--gold);text-shadow:0 0 18px var(--purple-glow);margin-right:10px}
nav{display:flex;gap:24px;flex-wrap:wrap;font:12px/1.6 'Cinzel',Georgia,serif;text-transform:uppercase;letter-spacing:.1em}
nav a{color:var(--text-muted)}nav a:hover{color:var(--gold)}
header p{color:var(--text-muted);overflow-wrap:anywhere;max-width:1100px;margin:14px 0}
h1,h2{font-family:'Cinzel',Georgia,serif;color:var(--gold-light);font-weight:500}
h1{font-size:clamp(32px,4vw,48px);line-height:1.2;margin:12px 0 18px;letter-spacing:.02em}
h2{font-size:23px;margin:0 0 18px}.eyebrow{color:var(--gold);letter-spacing:.17em;text-transform:uppercase;font-size:12px}
.status{display:inline-block;border:1px solid var(--border-magic);border-radius:24px;padding:6px 14px;font:12px/1.7 system-ui,sans-serif}
.status strong{color:var(--text-light)}main{max-width:1290px;padding:28px 24px;margin:auto}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px}
.card,section{min-width:0;background:linear-gradient(135deg,var(--bg-deep),var(--bg-night));
border:1px solid var(--border-magic);border-radius:12px;padding:24px;margin-bottom:20px}
.card{border-top:2px solid var(--gold);box-shadow:0 8px 24px rgba(0,0,0,.15)}
.card span{display:block;color:var(--text-muted);font:12px/1.6 system-ui,sans-serif}
.card strong{display:block;color:var(--gold-light);font:27px/1.4 'JetBrains Mono',monospace;margin-top:12px}
.chart{padding:12px;overflow:hidden;background:var(--bg-deep)}.plotly-graph-div{min-width:0}
.table-scroll{overflow:auto;max-height:650px}table{width:100%;border-collapse:collapse;font:12px/1.6 'JetBrains Mono',monospace}
td,th{text-align:left;padding:12px 14px;border-bottom:1px solid var(--border-magic);white-space:nowrap}
th{background:var(--bg-night);color:var(--gold-light);position:sticky;top:0}tr:nth-child(even){background:rgba(139,92,246,.05)}
.notice{padding:14px;background:#2b2020;border-left:3px solid var(--gold)}
code,pre{font-family:'JetBrains Mono',monospace;overflow-wrap:anywhere}pre{white-space:pre-wrap;font-size:12px}
details{margin-top:18px}summary{cursor:pointer;color:var(--gold)}footer{color:var(--text-muted);font-size:14px;margin:26px 0;text-align:center}
.js-plotly-plot .plotly .modebar{background:var(--bg-deep)!important}
.js-plotly-plot .plotly .modebar-btn path{fill:var(--text-muted)!important}
@media(max-width:600px){main{padding:18px 12px}header{padding:20px 20px 28px}
.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.card{padding:16px}.card strong{font-size:22px}
.chart{overflow-x:auto}.chart .plotly-graph-div{min-width:680px}section{padding:18px}}
"""


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
                marker_color="#8b5cf6",
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
                    colorscale=[[0, "#5b21b6"], [0.5, "#c4b5fd"], [1, "#f0d78c"]],
                    colorbar=dict(title="Cognitive"),
                    line=dict(width=1, color="#f0d78c"),
                ),
                hovertemplate="%{text}<br>Lines: %{x}<br>CC: %{y}<br>Cognitive: %{marker.color}<extra></extra>",
            )
        )
        scatter.add_hline(y=_threshold(result), line_dash="dash", line_color="#d4a853")
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
                marker_color="#8b5cf6",
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
            for side, color in [("before", "#a89ec9"), ("after", "#8b5cf6")]:
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
                        "#4ade80"
                        if c.cyclomatic_delta < 0
                        else "#fb923c" if c.cyclomatic_delta > 0 else "#a89ec9"
                    )
                    for c in ranked
                ],
            )
        )
        delta.add_vline(x=0, line_color="#d4a853")
        delta.update_layout(
            title="Change in cyclomatic complexity · lower is simpler",
            xaxis_title="After − before",
            yaxis=dict(autorange="reversed"),
        )
        distribution = go.Figure()
        for side, color in [("before", "#a89ec9"), ("after", "#8b5cf6")]:
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
            template="plotly_dark",
            paper_bgcolor="#12101f",
            plot_bgcolor="#12101f",
            font=dict(family="Arial, sans-serif", color="#f0e6d3"),
            title_font=dict(family="Georgia, serif", color="#f0d78c", size=20),
            hoverlabel=dict(bgcolor="#231d3d", bordercolor="#8b5cf6", font_color="#f0e6d3"),
            legend=dict(bgcolor="#12101f"),
            margin=dict(l=30, r=30, t=75, b=55),
            height=480,
        )
        figure.update_xaxes(gridcolor="rgba(139,92,246,.15)", zerolinecolor="#a89ec9")
        figure.update_yaxes(
            automargin=True, gridcolor="rgba(139,92,246,.15)", zerolinecolor="#a89ec9"
        )
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
<title>reducto · {title}</title><style>{_REPORT_STYLE}</style></head><body><header>
<div class="navigation"><a class="brand" href="https://mementomorri.github.io/reducto/"><span aria-hidden="true">✦</span>reducto</a>
<nav aria-label="Report navigation"><a href="#measurements">Measurements</a>
<a href="https://github.com/mementomorri/reducto/blob/main/docs/METRICS.md">Metric guide</a>
<a href="https://github.com/mementomorri/reducto">GitHub</a></nav></div>
<div class="eyebrow">The Shrinking Charm / metrics v{result.metrics_version}</div>
<h1>{title}</h1><p>{escape(_context(result))}</p>
<div class="status">Status: <strong>{'Complete' if result.complete else 'INCOMPLETE — see unavailable measurements'}</strong></div></header>
<main><div class="cards">{cards}</div>{errors}{empty}{charts}
<section id="measurements"><h2>All function measurements</h2>{notes}{_table(headers, rows, html=True)}</section>
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
