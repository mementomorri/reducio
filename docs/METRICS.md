# Metrics v2

`analyze`, `check`, and `compare` share the Python AST metric engine in
`reducto/metrics.py`. These scores replace the old text/indentation heuristics;
**do not compare v2 numbers to old reports**. Comparison remeasures both revisions
with the same installed engine and current configuration.

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
count. This is Reducto's explicit cyclomatic convention, not a promise of exact
agreement with other analyzers.

## Reducto cognitive score

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

The legacy `parse.get_complexity` import still works for snippet callers. It
dedents input, sums independent named-function scores when functions exist, and
otherwise measures the snippet as one block. Its LOC remains the whole snippet's
physical length. Invalid Python raises rather than returning fabricated metrics.
