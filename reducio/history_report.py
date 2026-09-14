"""Historical tables and a self-contained, interactive dashboard."""

import json
from pathlib import Path

from reducio.history import snapshot_metrics
from reducio.models import HistoryResult
from reducio.presentation import markdown_cell, table


def markdown_history(result: HistoryResult) -> str:
    rows = []
    for snapshot in result.snapshots:
        scores = snapshot_metrics(snapshot)
        rows.append(
            [
                snapshot.revision[:10],
                snapshot.committed_at[:10],
                snapshot.actual_scope or "absent",
                "complete" if snapshot.measurement.complete else "GAP",
                *[
                    scores.get(k) if scores.get(k) is not None else "—"
                    for k in (
                        "loc",
                        "functions",
                        "median_cc",
                        "p95_cc",
                        "hotspots",
                        "new_hotspots",
                        "resolved_hotspots",
                    )
                ],
            ]
        )
    notes = [f"{s.revision[:10]}: {note}" for s in result.snapshots for note in s.notes]
    notes += [
        f"{s.revision[:10]}: {d.file}: {d.message}"
        for s in result.snapshots
        for d in s.measurement.diagnostics
    ]
    return (
        "# reducio History\n\n"
        f"Scope: {markdown_cell(result.scope)} · {len(rows)} of up to {result.limit} first-parent commits. "
        f"Tool {result.tool_version}; metrics v{result.metrics_version}. "
        f"Head: {'complete' if result.head_complete else 'INCOMPLETE'}; "
        f"historical gaps: {sum(not s.measurement.complete for s in result.snapshots)}.\n\n"
        + table(
            [
                "Commit",
                "Date",
                "Source root",
                "Status",
                "LOC",
                "Functions",
                "Median CC",
                "p95 CC",
                "Hotspots",
                "New",
                "Resolved",
            ],
            rows,
        )
        + "\nAll snapshots are remeasured with the same current engine/configuration. Gaps are not zero scores; additions/removals are not matched-function improvements. HTML contains trends and drill-down.\n\n"
        + "\n\n".join(markdown_cell(note) for note in notes)
        + "\n"
    )


def html_history(result: HistoryResult) -> str:
    from reducio.visual_report import ReportError, html_report

    if not result.snapshots:
        raise ReportError("History contains no snapshots")

    payload = result.model_dump()
    payload["series"] = [snapshot_metrics(s) for s in result.snapshots]
    # A script element terminates at </script> even when its type is application/json.
    data = (
        json.dumps(payload, ensure_ascii=True)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    controls = """<section id="history"><h2>History · why is the code changing?</h2>
<p>Every point uses today's engine and configuration. Gaps mean unavailable measurements, not improvement.
Source-root transitions are labeled; function renames and ambiguous definitions are not guessed.</p>
<div class="history-controls"><label>From commit <select id="history-start"></select></label>
<label>Through commit <select id="history-end"></select></label>
<label>Inspect commit <select id="history-commit"></select></label>
<label>Function history <select id="history-function"></select></label></div>
<p id="history-status" role="status"></p><p id="history-range"></p></section>
<section class="chart"><div id="history-size"></div></section>
<section class="chart"><div id="history-complexity"></div></section>
<section class="chart"><div id="history-hotspots"></div></section>
<section class="chart"><div id="history-changes"></div></section>
<section><h2>Persistent hotspots · top 20 in selected range</h2>
<p>Hot snapshots / snapshots where this function was present and uniquely measured. Click a function to inspect its history.</p><div id="history-persistent" class="table-scroll"></div></section>
<section class="chart"><div id="history-function-chart"></div></section>
<section><h2>Selected commit</h2><p id="history-selected"></p><pre id="history-notes"></pre>
<div id="history-functions" class="table-scroll"></div></section>
<section><h2>Latest commit overview</h2><p>The overview below always describes the latest selected Git revision, not the historical commit selector.</p></section>
<style>.history-controls{display:flex;flex-wrap:wrap;gap:16px}.history-controls label{display:grid;grid-template-columns:minmax(0,1fr);gap:6px;flex:1 1 240px;min-width:0}
.history-controls select{width:100%;min-width:0;padding:10px;background:var(--bg-void);color:var(--text-light);border:1px solid var(--border-magic)}
#history-selected,#history-status,#history-range{overflow-wrap:anywhere}
select:focus-visible,button:focus-visible{outline:2px solid var(--gold)}
#history-persistent button{background:none;border:0;color:var(--gold);font:inherit;cursor:pointer;text-align:left}</style>"""
    script = Path(__file__).with_name("history_view.js").read_text(encoding="utf-8")
    return html_report(
        result.snapshots[-1].measurement,
        title="Code history",
        status_label="Latest snapshot",
        intro=controls,
        scripts=f'<script id="history-data" type="application/json">{data}</script><script>{script}</script>',
    )
