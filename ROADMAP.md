# reducto Roadmap

What is shipped today versus what is planned. This is the actionable index;
[`docs/DESIGN.md`](docs/DESIGN.md) holds the long-form product vision.

Status legend: **done** = shipped & tested · **planned** = intended next · **idea** = vision, not scheduled.

## Status: analysis/reporting expanded; modifier safety incomplete

The v1 feature set exists. Analysis now has syntax-aware metrics v2, offline HTML
and JSON reports, and Git revision comparison. Automatic modification is **not
production-safe**: known behavior-changing rewrites and dirty-tree recovery defects
remain. See [ASSESSMENT.md](docs/ASSESSMENT.md) and [TODO.md](TODO.md), items 19–24.

### Analysis and CI reporting — implemented

- Mandatory shared AST metrics for `analyze`, `check`, and `compare`; independent
  functions/methods, uncapped hotspot counts, explicit unavailable measurements.
- `compare --base ... --head ...`: complete changed-file functions, read-only Git
  snapshots, qualified-name matching, deltas and unmatched additions/removals.
- Markdown/JSON/offline HTML from the same result; overview and comparison charts.
- Independent overview and PR comparison jobs in the Analysis workflow, summaries
  and downloadable artifacts. Complexity verdicts are informational; actual errors fail.
- Main-only GitHub Pages publication of the latest successful overview, preserving
  the landing page and keeping PR/develop reports artifact-only.
- Rules and use: [METRICS.md](docs/METRICS.md), [CI.md](docs/CI.md).

The entries below record earlier delivered fixes. Their historical test counts
are not the current suite size, and individual guards do not prove semantic safety.

### P0 — Apply pipeline correctness — **done**

**Was:** heuristic `idiomatize` emitted one `FileChange` per idiom from a 2–3 line *snippet*, so
`difflib` produced snippet-relative hunks (`@@ -1,N @@`) that `apply_unified_diff` dropped at line 1 of
the whole file (clobbering the docstring/imports), and `_apply_hunk` never checked context.

**Fix (shipped):**
1. `reducto/agents/idiomatizer.py` — collect every idiom as a line span, apply spans to a copy of the
   file in reverse order, and emit **one** `FileChange` per file with full-file `original`/`modified`.
   Diffs are now file-relative and multi-edit drift is impossible.
2. `reducto/diff.py` — `_apply_hunk` verifies context (` `) and removed (`-`) lines against the target
   and raises `DiffError` on mismatch, so a stale/misaligned diff fails loudly and rolls back.
3. `reducto/services.py` — `_change_to_diff` splits on `"\n"` so `difflib` line numbers line up exactly
   with the applier.

**Guarded by:** `tests/unit/test_apply_idiomatize.py` (edit lands at the right lines, docstring intact,
result `ast.parse`s), `tests/unit/test_diff.py::test_context_mismatch_raises`, and
`tests/e2e/test_cli_smoke.py::test_idiomatize_never_breaks_valid_python` (no valid file becomes invalid).

### P1 — `deduplicate` is honest — **done**

`deduplicate` proposes a shared `utils/<symbol>_dedup.py` module and now says so plainly — plan text,
the `FileChange` description, and `--help` all state it is a **suggestion only** that does not rewrite
call sites. Missing embeddings no longer fail silently: with the `[embeddings]` extra absent it returns a
clear "install the extra" message instead of an empty result.
(Real call-site rewriting remains a post-v1 feature — see Near-term.)

### P2 — Apply hardening — **done**

- Post-apply `ast.parse` of every changed `.py` in `workspace.apply_changes_safe`; any `SyntaxError`
  rolls the batch back and reports failure (closes the "test-less repo commits broken code" gap).
- `pattern` auto-detect writes suggestions to **new advisory modules** (`strategies/…`, `factories/…`)
  instead of `original=""` against the source file — which previously prepended a template into it.
- The dirty-tree prompt (`cli._check_git`) and `--yes`/`--dry-run` gating are unchanged.

### P3 — Initial semantic guards — **partial; safety milestone incomplete**

These specific guards shipped, but the later audit found additional semantic and
recovery defects. They remain release blockers:

- `idiomatize` no longer rewrites a for/append loop whose value, iterable, or filter reads the
  accumulator (e.g. order-preserving dedup `if v not in u: u.append(v)`) — that silently changed
  behaviour. It also skips any file that doesn't `ast.parse` (can't safely rewrite/validate it), so one
  broken file no longer rolls back the whole batch. (`agents/idiomatizer.py`)
- `pattern singleton` writes a NEW advisory module (`singletons/…`) like every other pattern instead of
  overwriting the source file — which used to discard the original code. (`agents/pattern.py`)
- `apply` refuses any whole-file rewrite that drops a top-level/nested `def`/`class`
  (`services._def_names`) — a net for LLM rewrites and future template bugs.
- Historical word-boundary metric fix: prevented `for`/`or` substring double-counting.
  Now superseded by syntax-aware metrics v2 (`metrics.py`).
- CLI robustness: unknown `pattern` names and non-directory paths exit `2` with a message (no traceback);
  `report` falls back cleanly when no report exists; `idiomatize` now echoes apply success/failure;
  `deduplicate` degrades to the "install the extra" message instead of crashing when `chromadb` is
  absent.

**Guarded by:** `tests/unit/test_idiomatizer.py::test_idiomatize_skips_accumulator_referencing_loop`,
`tests/unit/test_pattern_agent.py::test_singleton_pattern_writes_advisory_module_not_source`,
`tests/unit/test_apply_guard.py`, `tests/unit/test_complexity.py::test_cyclomatic_counts_for_loop_once`,
and CLI cases in `tests/e2e/test_cli_smoke.py`. Suite at 112 tests / ~73% coverage.

## Current capabilities

| Capability | Status | Notes |
|------------|--------|-------|
| `analyze` — AST symbols + function-level metrics v2 | done | Static, no LLM; Markdown/JSON/HTML reports. |
| `compare` — committed revision comparison | done | Changed-file function deltas; independent PR job. |
| `idiomatize` — comprehensions, `is None`, truthiness, membership | partial safety | Planning/apply exist; known behavior-changing cases remain. Optional LLM whole-file rewrite. |
| `deduplicate` — embedding clustering → proposed `utils/<symbol>_dedup.py` | done (suggest-only) | Honestly labeled; does **not** remove dupes or rewrite call sites. See Near-term. |
| `pattern` — factory/strategy/observer/singleton templates | done | Default paths write advisory modules. Opt-in LLM via model configuration. |
| `check` — naming, function length, per-function cyclomatic complexity | done | `critical` when CC ≥ 2× threshold. |
| Unified thresholds | done | `check` and `analyze` both read `AppConfig.complexity_thresholds`. |
| Apply — checkpoints, validated diffs, syntax checks, rollback attempts | partial safety | Dirty-state preservation and exceptional recovery remain blockers. |
| Session persistence / replay (`apply`, `sessions`, `report`) | done | JSON under `.reducto/sessions/`. |
| LiteLLM model routing (local Ollama / remote) | done | Opt-in via `--model`; tier config lives in `LLMRouter`. |
| Config: `.reducto.yaml` + `REDUCTO_*` env overrides | done | |

## Enhancement opportunities

These opportunities capture the gap between the original landing-page claims and
the tool. They are **not shipped capabilities or delivery commitments**. The
landing page now describes current behavior; [ADVERTISING_AUDIT.md](docs/ADVERTISING_AUDIT.md)
preserves the original comparison. Safety items remain release blockers, not
optional polish. Ordered from immediate clarity/safety work to broader features:

- [ ] **Review and result clarity:** show unified diffs before approval, session IDs,
  actual apply outcomes and failure exit codes, and heuristic/model/fallback provenance.
  Decide whether to expose the existing commit configuration as a supported CLI flag.
- [ ] **Reliable recovery — release blocker:** preserve staged, unstaged, and
  untracked pre-existing work; recover from validation/runner exceptions; distinguish
  actual rollback success and tests passed/failed/not run. See TODO 22–24.
- [ ] **Behavior-preserving idioms — release blocker:** fix literal, accumulator,
  alias, and evaluation-order changes; define supported preconditions and test
  behavior before/after. Skip unsupported cases. See TODO 19–21.
- [ ] **Enforced local-only mode:** explicit remote consent, provider visibility,
  safe prompt logging, and disclosure of model/embedding downloads.
- [ ] **Cognitive threshold policy:** define how CC and cognitive thresholds select
  findings, then apply it consistently to analysis, checks, comparisons, and charts.
- [ ] **More validated idioms:** add narrowly scoped context-manager, enumerate,
  f-string, and other transformations only with tested safety preconditions.
- [ ] **Dependency/reference mapping:** resolve imports, symbols, and callers for
  impact analysis; report ambiguity instead of guessing.
- [ ] **Real deduplication and pattern integration:** use reference analysis to
  rewrite imports/callers and remove originals only when validated. Measure actual
  LOC/complexity changes; copied utilities and templates alone are not compression.
- [ ] **Release parity checks:** test documented commands/extras against a selected
  published release in a clean environment and provide release-specific guidance.

## Near-term (planned)

- **More idioms (heuristic tail)** — remaining patterns in `test-python-code/python/style/non_idiomatic.py`
  that need multi-line body rewrites: `enumerate` (drop `range(len(...))`), f-strings, `with`-statement
  context managers, `itertools.product`, `str.join`. Require supported preconditions
  and behavior tests; opt-in LLM output is not a substitute for validation.
- **Real deduplication** — rewrite call sites to import the extracted util, not just emit the module.
  Safe interim options: rewrite only when duplicates share a name, or gate behind an explicit `--rewrite`
  flag. Needs the cross-file symbol layer below.

## Mid-term

- **Cross-file impact analysis** — re-introduce an LSP/symbol-graph layer *only when a command consumes it*
  (dead-code detection, safe-rename impact, real dedup rewrite).
- **Further reporting** — historical trends, hosted PR previews, and optional PR comments.
- **CI mode** — non-interactive `--ci` / pre-commit integration with meaningful exit codes.

## Vision (from DESIGN.md — not scheduled)

- Multi-agent orchestration (LangGraph) · pgvector persistent idiom memory · MCP server · autonomous
  PR-review mode · PDF reports · multi-language support.
