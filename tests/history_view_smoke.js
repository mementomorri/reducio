/* Exercise the shipped controller without a browser dependency in Python CI. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

class Node {
  constructor() { this.children = []; this.value = ""; this.textContent = ""; this.listeners = {}; }
  append(child) {
    this.children.push(child);
    if (this.children.length === 1 && child.value !== "") this.value = String(child.value);
  }
  replaceChildren(child) { this.children = [child]; }
  createTHead() { const n = new Node(); this.append(n); return n; }
  createTBody() { return this.createTHead(); }
  insertRow() { return this.createTHead(); }
  insertCell() { return this.createTHead(); }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  focus() {}
}
const nodes = new Map(), plots = new Map();
const element = id => {
  if (!nodes.has(id)) nodes.set(id, new Node());
  return nodes.get(id);
};
const data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
// An untrusted subject must stay text, and ambiguous names must not be joined.
data.snapshots[1].subject = '<img src=x onerror="throw 1">';
element("history-data").textContent = JSON.stringify(data);
const context = {
  Node,
  document: {getElementById: element, createElement: () => new Node()},
  Plotly: {react: (target, traces, layout) => plots.set(target, {traces, layout})},
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../reducio/history_view.js"), "utf8"), context);
const plot = id => plots.get(element(`history-${id}`));
assert.equal(plots.size, 5);
assert.deepEqual(Array.from(plot("size").traces[0].y), [0, 3, null, 1]);
assert.equal(plot("size").traces[1].yaxis, "y2");
assert.equal(plot("hotspots").traces[1].yaxis, "y2");
assert.equal(plot("size").traces[0].connectgaps, false);
assert.equal(plot("changes").traces[0].y[3], null);
assert.match(element("history-selected").textContent, /sample revision/);
element("history-commit").value = "2";
element("history-commit").listeners.change();
assert.match(element("history-notes").textContent, /syntax/);
element("history-start").value = "1";
element("history-end").value = "3";
element("history-start").listeners.change();
assert.match(element("history-status").textContent, /3 snapshots selected; 1 unavailable/);
assert.match(element("history-range").textContent, /Physical LOC: -2/);
// Persistent ranking has one row with 1 hot / 2 uniquely present snapshots.
const rows = element("history-persistent").children[0].children[1].children;
assert.equal(rows.length, 1);
assert.equal(rows[0].children[1].textContent, 1);
assert.equal(rows[0].children[2].textContent, 2);
rows[0].children[0].children[0].listeners.click();
assert.deepEqual(Array.from(plot("function-chart").traces[0].y), [2, null, 1]);
assert.equal(plot("function-chart").traces[2].yaxis, "y2");
// Reversed endpoints select the same chronological interval.
element("history-start").value = "3";
element("history-end").value = "1";
element("history-end").listeners.change();
assert.deepEqual(Array.from(plot("function-chart").traces[0].y), [2, null, 1]);
// A snapshot with duplicate identities is excluded from per-function trends.
data.snapshots[1].measurement.functions.push(data.snapshots[1].measurement.functions[0]);
nodes.clear(); plots.clear(); element("history-data").textContent = JSON.stringify(data);
vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../reducio/history_view.js"), "utf8"), context);
element("history-function").value = JSON.stringify(["a.py", "f", "function"]);
element("history-function").listeners.change();
assert.deepEqual(Array.from(plot("function-chart").traces[0].y), [null, null, null, 1]);
console.log("Offline dashboard controller checks passed");
