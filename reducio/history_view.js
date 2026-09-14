/* Offline history views: input is embedded JSON, never executable source/HTML. */
(() => {
  const history = JSON.parse(document.getElementById("history-data").textContent);
  const snapshots = history.snapshots, series = history.series;
  const element = id => document.getElementById(`history-${id}`);
  const identity = f => JSON.stringify([f.file, f.qualified_name, f.kind]);
  const label = f => `${f.file} · ${f.qualified_name} (${f.kind})`;
  const escape = text => String(text).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const option = (select, value, text) => {
    const node = document.createElement("option"); node.value = value; node.textContent = text; select.append(node);
  };
  const functions = new Map();
  snapshots.forEach((snapshot, i) => {
    const name = `${snapshot.revision.slice(0, 10)} · ${snapshot.committed_at.slice(0, 10)} · ${snapshot.subject}`;
    ["start", "end", "commit"].forEach(id => option(element(id), i, name));
    snapshot.measurement.functions.forEach(f => functions.set(identity(f), f));
  });
  option(element("function"), "", "Choose a function or click a persistent hotspot");
  [...functions].sort((a, b) => label(a[1]).localeCompare(label(b[1]))).forEach(([key, f]) => option(element("function"), key, label(f)));
  element("end").value = element("commit").value = snapshots.length - 1;
  const range = () => {
    const lo = Number(element("start").value), hi = Number(element("end").value);
    return Array.from({length: Math.abs(hi - lo) + 1}, (_, i) => Math.min(lo, hi) + i);
  };
  const colors = ["#8b5cf6", "#f0d78c", "#4ade80", "#fb923c"];
  function plot(id, title, names, values, bars = false, rightAxis = []) {
    const indices = range();
    const traces = names.map((name, index) => ({
      name: escape(name), x: indices.map(i => snapshots[i].revision.slice(0, 10)),
      y: indices.map(i => values[index](i) ?? null), connectgaps: false,
      type: bars ? "bar" : "scatter", mode: "lines+markers",
      marker: {color: colors[index % colors.length]},
      yaxis: rightAxis.includes(index) ? "y2" : "y",
    }));
    Plotly.react(element(id), traces, {
      title: {text: escape(title)}, height: 390, paper_bgcolor: "#12101f", plot_bgcolor: "#12101f",
      font: {color: "#f0e6d3"}, margin: {t: 65, b: 80, l: 65, r: rightAxis.length ? 65 : 25},
      xaxis: {type: "category", title: {text: "Commits · first-parent order"}},
      yaxis: {title: {text: rightAxis.length ? escape(names[0]) : "Score / count"}, rangemode: "tozero"},
      ...(rightAxis.length ? {yaxis2: {title: {text: escape(names[rightAxis[0]])}, overlaying: "y", side: "right", rangemode: "tozero"}} : {}),
      legend: {orientation: "h"}, barmode: "group",
    }, {responsive: true, displaylogo: false});
  }
  function table(id, headers, rows) {
    const table = document.createElement("table"), head = table.createTHead().insertRow();
    headers.forEach(text => { const cell = document.createElement("th"); cell.scope = "col"; cell.textContent = text; head.append(cell); });
    const body = table.createTBody();
    rows.forEach(row => {
      const tr = body.insertRow(); row.forEach(value => {
        const cell = tr.insertCell();
        if (value instanceof Node) cell.append(value); else cell.textContent = value ?? "—";
      });
    });
    element(id).replaceChildren(table);
  }
  function functionHistory() {
    const key = element("function").value, f = functions.get(key);
    const value = (i, field) => {
      if (!snapshots[i].measurement.complete) return null;
      const matches = snapshots[i].measurement.functions.filter(f => identity(f) === key);
      return matches.length === 1 ? matches[0][field] : null;
    };
    plot("function-chart", f ? label(f) : "Select a function to explore its history", ["Cyclomatic", "Cognitive", "Physical lines"],
      [i => value(i, "cyclomatic_complexity"), i => value(i, "cognitive_complexity"), i => value(i, "lines_of_code")], false, [2]);
  }
  function inspect() {
    const s = snapshots[Number(element("commit").value)];
    element("selected").textContent = `${s.revision} · ${s.committed_at} · ${s.subject} · Source: ${s.actual_scope ?? "absent"}`;
    element("notes").textContent = [
      ...s.notes, ...s.measurement.diagnostics.map(d => `${d.file}: ${d.message}`),
      ...(s.comparison_available ? [] : ["Previous-commit deltas unavailable."]),
      ...s.changes.filter(c => c.status === "removed").map(c => `Removed: ${label(c.before)}`),
    ].join("\n");
    table("functions", ["Function", "Line", "CC", "Cognitive", "LOC", "Change vs previous", "Δ CC", "Δ cognitive"], s.measurement.functions.map(f => {
      const matches = s.changes.filter(c => c.after && identity(c.after) === identity(f) && c.after.line === f.line);
      const c = matches.length === 1 ? matches[0] : null;
      return [label(f), f.line, f.cyclomatic_complexity, f.cognitive_complexity, f.lines_of_code, c?.status, c?.cyclomatic_delta, c?.cognitive_delta];
    }));
  }
  function redraw() {
    const indices = range(), gaps = indices.filter(i => !snapshots[i].measurement.complete).length;
    element("status").textContent = `${indices.length} snapshots selected; ${gaps} unavailable. ${history.unique_blobs_analyzed} unique blobs analyzed once each. Metrics v${history.metrics_version}; tool ${history.tool_version}.`;
    const first = series[indices[0]], last = series[indices.at(-1)];
    element("range").textContent = "Endpoint changes (not a quality verdict): " + [
      ["Physical LOC", "loc"], ["Functions", "functions"], ["p95 CC", "p95_cc"],
      ["p95 cognitive", "p95_cognitive"], ["Hotspots", "hotspots"],
    ].map(([name, key]) => {
      if (first[key] == null || last[key] == null) return `${name}: unavailable`;
      const delta = last[key] - first[key]; return `${name}: ${delta > 0 ? "+" : ""}${delta}`;
    }).join(" · ");
    plot("size", "Repository size · growth is not itself a regression", ["Physical lines", "Functions"], [i => series[i].loc, i => series[i].functions], false, [1]);
    plot("complexity", "Typical and high-end function complexity", ["Median CC", "p95 CC", "Median cognitive", "p95 cognitive"], ["median_cc", "p95_cc", "median_cognitive", "p95_cognitive"].map(k => i => series[i][k]));
    plot("hotspots", "Hotspots · count and share of measured functions (%)", ["Hotspots", "Hotspot share (%)"], [i => series[i].hotspots, i => series[i].hotspot_share], false, [1]);
    plot("changes", "New and resolved hotspots vs the previous commit", ["New", "Resolved"], [i => series[i].new_hotspots, i => series[i].resolved_hotspots], true);
    const ranking = new Map(), threshold = history.configuration.complexity_thresholds.cyclomatic_complexity;
    indices.forEach(i => {
      const snapshot = snapshots[i]; if (!snapshot.measurement.complete) return;
      const counts = new Map(); snapshot.measurement.functions.forEach(f => counts.set(identity(f), (counts.get(identity(f)) ?? 0) + 1));
      snapshot.measurement.functions.forEach(f => {
        const key = identity(f); if (counts.get(key) !== 1) return;
        const entry = ranking.get(key) ?? {f, present: 0, hot: 0}; entry.present++; entry.f = f;
        if (f.cyclomatic_complexity >= threshold) entry.hot++; ranking.set(key, entry);
      });
    });
    const rows = [...ranking].filter(([, v]) => v.hot).sort((a, b) => b[1].hot - a[1].hot || label(a[1].f).localeCompare(label(b[1].f))).slice(0, 20).map(([key, entry]) => {
      const button = document.createElement("button"); button.textContent = label(entry.f);
      button.addEventListener("click", () => { element("function").value = key; functionHistory(); element("function").focus(); });
      return [button, entry.hot, entry.present, entry.f.cyclomatic_complexity];
    });
    table("persistent", ["Function", "Hot snapshots", "Present snapshots", "Last measured CC"], rows);
    functionHistory();
  }
  ["start", "end"].forEach(id => element(id).addEventListener("change", redraw));
  element("commit").addEventListener("change", inspect);
  element("function").addEventListener("change", functionHistory);
  redraw(); inspect();
})();
