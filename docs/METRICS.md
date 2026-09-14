# Metrics v2

`analyze`, `check`, `compare`, `history`, and apply-session measurements share the Python AST metric engine in
`reducio/metrics.py`. These scores replace the old text/indentation heuristics;
**do not compare v2 numbers to old reports**. Comparison remeasures both revisions
with the same installed engine and current configuration.

## Apply-session reports

All modifying commands accept `--report` for Markdown and structured JSON.
Measurements cover whole affected Python files before edits, attempted edits
after syntax validation, and files retained after success/recovery. Matched
functions show cyclomatic/cognitive deltas; additions and removals are separate.
Ambiguous qualified names are labeled, not guessed. Missing or incomplete
measurements are unavailable, never fake zeros; maintainability is not measured.
Test/recovery statuses accompany the metrics. See [SAFETY.md](SAFETY.md).

## Scope and lines

- Each named function, async function, and method is measured independently.
  Nested functions reset nesting; their decisions are not added to their parent.
- Classes are symbols, not scored containers. Module/class-body decisions do not
  contribute to function scores. Lambdas are inline expressions, not separate
  function records; their decisions contribute to the enclosing function.
- Function scoring visits its body, not decorators, defaults, or annotations.
- File LOC is `len(source.splitlines())`: physical lines, including comments and
  blanks; a trailing newline does not add a line. Empty files have zero lines.
- Function LOC spans the first decorator (or `def`) through the last AST statement.
  It includes nested definitions and internal comments/blanks; trailing comments
  outside that AST span are excluded. Function LOC spans can overlap: do not sum
  them to obtain file LOC. The reported location points to `def`.
- Parse failures are explicit unavailable measurements, never zero complexity.
  Reports preserve valid files but are marked incomplete; CLI exit status is 1.
  History is the exception for **older** snapshots: they remain visible gaps;
  an incomplete latest snapshot still exits 1.

## Cyclomatic score

Start at **1 per function**, then add:

| Syntax | Increment |
| --- | --- |
| `if`, `elif`, conditional expression | 1 each |
| `for`, `async for`, `while` | 1 each |
| `except` / `except*` handler | 1 each |
| `and`, `or` | 1 per operator between operands |
| Comprehension/generator | 1 per generator and per filter |
| `match` cases | 1 per non-default case; 1 per guard |
| `with`, `async with` | 1 per statement, independent of context count |
| `assert` | 1 each |

`else`, `try`, `finally`, `return`, calls, and pattern alternatives (`case 1 | 2`)
add no separate decision. An unguarded wildcard/capture case adds none. Decisions
inside expressions still count. Comments, docstrings, and string contents never
count. This is Reducio's explicit cyclomatic convention, not a promise of exact
agreement with other analyzers.

## Reducio cognitive score

Starts at **0**. This custom, nesting-weighted score is **not Sonar-compatible**.

- `if`, loops, conditional expressions, handlers, and comprehension generators /
  filters add `1 + current nesting depth`; their bodies deepen nesting.
- `elif` adds 1 without a nesting penalty; a final `else` adds 1. An actual
  `else: if` remains nested, not an `elif`. Loop `else` also adds 1.
- Each homogeneous AST Boolean group adds 1. Directly nested groups of the same
  operator are merged; a different operator starts another group.
- Comprehension generators and filters deepen nesting successively, including
  for the element/key/value expression.
- `match` adds `1 + depth` once. Case bodies deepen nesting; each guard adds
  `1 + depth + 1` before its own expression decisions.
- `with`, `assert`, `try`, and `finally` add no cognitive cost or nesting level.
  Recursion and jumps have no special cognitive penalty.

Examples: a branch-free function is `(CC=1, cognitive=0)`; three nested `if`s
are `(4, 6)`; `a and b and c` is `(3, 1)`; `[x for x in xs if x]` is `(3, 3)`.

## Reporting and comparison

Hotspots use `CC >= complexity_thresholds.cyclomatic_complexity` (default 10).
The count and JSON/HTML data include **all** hotspots/functions; terminal and
Markdown lists and ranked charts show at most 20. Distributions use all applicable
function records, not just hotspots.

`compare` selects changed Python files, then measures their **whole functions on
both sides**, not isolated added/deleted lines. A function elsewhere in a changed
file is included as unchanged context. Identity is file path plus qualified name;
Git-detected file renames preserve identity. Function renames and ambiguous repeated
definitions are shown as unmatched additions/removals, not guessed refactors.

For matched functions, deltas are `after - before`. Lower CC/cognitive with neither
rising is improved; higher with neither falling is regressed; opposing directions
are mixed; both equal is unchanged. LOC does not decide the verdict. Additions and
removals have no numeric delta. New/resolved hotspots include added/removed hot
functions as well as threshold crossings. An unreadable side excludes that file
from matching rather than making it look removed or improved.

JSON includes `metrics_version`, completeness, configuration, exact Git revisions
(comparison), all measurements, matches, and diagnostics. No repository-wide
improvement percentage or single quality score is claimed. Complexity is a useful
review signal, not evidence that behavior was preserved.

Comparison JSON also records `head_source` (`commit` or `worktree`), `gate_threshold`
and `gate_failed`. Working-tree mode labels the SHA as a HEAD anchor; it is not a
content hash for uncommitted files. Gates are opt-in: `new-hotspots` uses threshold
crossings and added hotspots, while `regressions` additionally includes both
regressed and mixed matched functions. Unchanged debt and non-hot additions do
not fail either gate. Quality-rule suppression is separate and never changes
these metrics or hotspot counts.

## Historical trends

History schema v1 embeds metrics v2 measurements and resolved configuration/tool
version. Every selected first-parent commit is remeasured with that **same current
engine/configuration**; old report versions and old configuration files are not
mixed into a trend. Unchanged Git blobs are parsed once per run, with file paths
remapped per snapshot. No persistent cache is required.

- Size: sum of physical **file** LOC and number of measured functions.
- Complexity: median and nearest-rank p95 of each function score. For sorted `n`
  values, p95 is value `ceil(0.95 × n)` (1-based). Empty sets yield unavailable
  medians/p95, not zero.
- Hotspots: count and `100 × count / measured functions`; empty sets have no share.
- New/resolved: changes versus the preceding selected first-parent snapshot, not
  the previous successful measurement. The first point and either side of a gap
  have unavailable deltas. Added/removed hotspots are counted but are not claimed
  as matched-function improvements.
- Persistence: hot snapshots / snapshots in the selected range where that
  function was present, complete and uniquely identified. It is not elapsed time.

History identity is canonical path + qualified name + kind; explicit source-root
aliases preserve root transitions and are disclosed on the relevant commits.
History does not infer other file/function renames. Repeated definitions are
excluded from persistent/function trends rather than arbitrarily joined; commit
tables retain them. A missing source root or any invalid/unreadable selected file
makes that entire snapshot a chart gap, with partial valid measurements available
for inspection. Charts never connect across these gaps.

The legacy `parse.get_complexity` import still works for snippet callers. It
dedents input, sums independent named-function scores when functions exist, and
otherwise measures the snippet as one block. Its LOC remains the whole snippet's
physical length. Invalid Python raises rather than returning fabricated metrics.
