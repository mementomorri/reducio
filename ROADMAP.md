# reducio Roadmap

What is shipped today versus what is planned. This is the actionable index;
[`docs/DESIGN.md`](docs/DESIGN.md) holds the long-form product vision.

Status legend: **done** = shipped & tested · **planned** = intended next · **idea** = vision, not scheduled.

## Status: analysis/reporting implemented; guarded modifiers remain experimental

The v1 feature set exists. Analysis now has syntax-aware metrics v2, offline HTML
and JSON reports, and Git revision comparison. Automatic modification is **not
production-safe**. Sections 1–4 safeguards are implemented, including conservative
idioms and scoped, verified recovery, but do not prove semantic equivalence.
See [safety limits](docs/SAFETY.md) and the enhancement opportunities below.

### Daily review and history — implemented locally

- [x] Rebuilt Git history (default 100 first-parent commits), consistent current
  metrics, explicit old-root aliases and gaps, run-local batched blob reuse.
- [x] Offline trend dashboard: size, median/p95 complexity, hotspot count/share,
  new/resolved hotspots, persistent hotspots and commit/range/function exploration.
- [x] Main-only history CI and Pages, alongside the standalone latest overview;
  no persistent data branch and no PR publication.
- [x] `compare --against` and explicit `--worktree`, optional PR warnings and
  new-hotspot/regression gates; report-only remains the default.
- [x] Per-rule severity/off and per-path quality ignores with visible suppressed
  findings and unsuppressible source errors.
- [x] Bounded f-string and dictionary-get idioms with behavior/encoding tests.

These changes are in source; a new PyPI/PyApp release and Pages deployment are
separate maintainer actions. See [usage](docs/CI.md) and [verification](docs/TEST_IMPLEMENTATION.md).

### Reliability and code reduction — implemented locally

Shared Python AST parsing, byte-preserving scans and versioned whole-file plans,
AST naming/pattern checks, run-local NumPy similarity, shared rendering/matching,
atomic persistence, and a shared release verification gate replace duplicate or
unused machinery. Tests now enforce 90% combined statement/branch coverage.
See [migration notes](docs/MIGRATION.md) and [verification](docs/TEST_IMPLEMENTATION.md).

### Analysis and CI reporting — implemented

- Mandatory shared AST metrics for `analyze`, `check`, and `compare`; independent
  functions/methods, uncapped hotspot counts, explicit unavailable measurements.
- `compare --base ... --head ...`: complete changed-file functions, read-only Git
  snapshots, qualified-name matching, deltas and unmatched additions/removals.
- Markdown/JSON/offline HTML from the same result; overview and comparison charts.
- Independent overview and PR comparison jobs in the Analysis workflow, summaries
  and downloadable artifacts. Complexity verdicts are informational by default;
  opt-in gates enforce policy, and actual errors fail.
- Main-only GitHub Pages publication of rebuilt history and the latest overview, preserving
  the landing page and keeping PR/develop reports artifact-only.
- Rules and use: [METRICS.md](docs/METRICS.md), [CI.md](docs/CI.md).

### CLI clarity and configuration — implemented

- Plans say proposed, expose session IDs and dry-run paths, skip empty application,
  and return nonzero on failed apply. Saved-plan replay warns about dirty Git state.
- Configuration precedence: explicit CLI → environment → selected YAML → defaults;
  services preserve resolved settings. `--no-verbose` disables detail; `--quiet`
  controls progress independently. Invalid configurations/targets exit 2 cleanly.
- Progress stages/heartbeats, canonical repository links, CI setup guide, and
  normal/forced-color help regression tests. Safety docs state remaining limits.
- These changes complete TODO section 1, not the behavior/recovery safety milestone.

The entries below record earlier delivered fixes. Their historical test counts
are not the current suite size, and individual guards do not prove semantic safety.

### P0 — Apply pipeline correctness — **done**

Historical implementation below: the reliability cleanup subsequently removed
the diff engine. Exact whole-file byte checks and `test_workspace.py` now provide
the stale-plan guard; unified diffs remain previews only.

**Was:** heuristic `idiomatize` emitted one `FileChange` per idiom from a 2–3 line *snippet*, so
`difflib` produced snippet-relative hunks (`@@ -1,N @@`) that `apply_unified_diff` dropped at line 1 of
the whole file (clobbering the docstring/imports), and `_apply_hunk` never checked context.

**Fix (shipped):**
1. `reducio/agents/idiomatizer.py` — collect every idiom as a line span, apply spans to a copy of the
   file in reverse order, and emit **one** `FileChange` per file with full-file `original`/`modified`.
   Diffs are now file-relative and multi-edit drift is impossible.
2. `reducio/diff.py` — `_apply_hunk` verifies context (` `) and removed (`-`) lines against the target
   and raises `DiffError` on mismatch, so a stale/misaligned diff fails loudly and rolls back.
3. `reducio/services.py` — `_change_to_diff` splits on `"\n"` so `difflib` line numbers line up exactly
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

### P3 — Initial semantic guards — historical milestone

These specific guards shipped, but the later audit found additional semantic and
recovery defects. TODO section 3 now addresses those defects with conservative
rules and file snapshots; see the current capabilities and [safety model](docs/SAFETY.md).

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
| `compare` — revisions or explicit working tree | done | Merge-base convenience, changed-file deltas, opt-in PR gates/annotations. |
| `history` — rebuilt first-parent trends | implemented locally | Configurable 100-commit default, gaps, persistent hotspots and offline drill-down. |
| `idiomatize` — comprehensions, `is None`, truthiness, membership, f-strings, dict get | bounded support | AST/token-aware, closed built-in cases only; uncertain cases skipped. Optional unverified LLM proposals. |
| `deduplicate` — embedding clustering → proposed `utils/<symbol>_dedup.py` | done (suggest-only) | Honestly labeled; does **not** remove dupes or rewrite call sites. See Near-term. |
| `pattern` — factory/strategy/observer/singleton templates | done | Default paths write advisory modules. Opt-in LLM via model configuration. |
| `check` — naming, function length, per-function cyclomatic complexity | done | Severity gates, per-rule overrides and per-path suppression; source errors remain fatal. |
| Unified thresholds | done | `check` and `analyze` both read `AppConfig.complexity_thresholds`. |
| Apply — validated diffs, file snapshots, syntax/metrics checks | done (bounded) | No Git writes; opt-in tests; verified scoped recovery and explicit failures. Not crash-proof/multi-file atomic. |
| Session persistence / replay (`apply`, `sessions`, `report`) | done | JSON under `.reducio/sessions/`. |
| Explicit compatible APIs | done | Optional `[llm]`; OpenAI Chat Completions or Anthropic Messages format, explicit model/custom URL. No tiers/discovery. |
| Config: `.reducio.yaml` + `REDUCIO_*` env overrides | done | |

## Enhancement opportunities

These opportunities capture the gap between the original landing-page claims and
the tool. They are **not shipped capabilities or delivery commitments**. The
landing page now describes current behavior; [ADVERTISING_AUDIT.md](docs/ADVERTISING_AUDIT.md)
preserves the original comparison. The scoped section 3 safeguards are complete;
broader semantic guarantees are not claimed. Ordered from clarity to broader features:

- [ ] **Review and result clarity:** session IDs, target-local report paths, actual
  apply outcomes, failure exit codes, unified diff previews, and persisted
  heuristic/model/fallback provenance are implemented.
  Apply reports now include metrics and test/recovery outcomes; automatic commits
  and the old commit configuration have been removed.
- [x] **Scoped recovery:** per-attempt file snapshots preserve pre-existing state;
  validation/runner exceptions trigger verified recovery. Explicit test/recovery
  statuses and retained backups are implemented. No crash-atomic guarantee.
- [x] **Conservative idioms:** AST/token-aware edits, tested closed built-in
  prerequisites, and skipping uncertain accumulator/alias/evaluation cases.
  Broader semantics and model rewrites remain review-dependent.
- [ ] **Enforced local-only mode:** explicit remote consent, provider visibility,
  safe prompt logging, and disclosure of model/embedding downloads.
- [ ] **Cognitive threshold policy:** define how CC and cognitive thresholds select
  findings, then apply it consistently to analysis, checks, comparisons, and charts.
- [ ] **More validated idioms:** context-manager, enumerate and wider f-string/get
  support still need tested safety preconditions; closed-value f-string/get cases exist.
- [ ] **Dependency/reference mapping:** resolve imports, symbols, and callers for
  impact analysis; report ambiguity instead of guessing.
- [ ] **Real deduplication and pattern integration:** use reference analysis to
  rewrite imports/callers and remove originals only when validated. Measure actual
  LOC/complexity changes; copied utilities and templates alone are not compression.
- [ ] **Release parity checks:** test documented commands/extras against a selected
  published release in a clean environment and provide release-specific guidance.

## Near-term (planned)

- **More idioms (heuristic tail)** — remaining patterns in `test-python-code/python/style/non_idiomatic.py`
  that need multi-line body rewrites: `enumerate` (drop `range(len(...))`), wider string formatting, `with`-statement
  context managers, `itertools.product`, `str.join`. Require supported preconditions
  and behavior tests; opt-in LLM output is not a substitute for validation.
- **Real deduplication** — rewrite call sites to import the extracted util, not just emit the module.
  Safe interim options: rewrite only when duplicates share a name, or gate behind an explicit `--rewrite`
  flag. Needs the cross-file symbol layer below.

## Mid-term

- **Cross-file impact analysis** — re-introduce an LSP/symbol-graph layer *only when a command consumes it*
  (dead-code detection, safe-rename impact, real dedup rewrite).
- **Further reporting** — hosted PR previews and optional PR comments; rebuilt
  history trends and Actions warning annotations are implemented locally.
- **CI mode** — non-interactive `--ci` / pre-commit integration with meaningful exit codes.

## Vision (from DESIGN.md — not scheduled)

- Multi-agent orchestration (LangGraph) · pgvector persistent idiom memory · MCP server · autonomous
  PR-review mode · PDF reports · multi-language support.
