# reducto Roadmap

What is shipped today versus what is planned. This is the actionable index;
[`docs/DESIGN.md`](docs/DESIGN.md) holds the long-form product vision.

Status legend: **done** = shipped & tested · **planned** = intended next · **idea** = vision, not scheduled.

## Status: v1 ready (analyzer + modifier)

**Goal.** A tool you can trust on a real Python repo: it *analyzes* safely (read-only) and *modifies*
code only when the edit is provably correct and reversible.

Both lanes now meet that bar:

- **v1-analyzer:** `analyze`, `check`, and every `--dry-run` / `--report` flow — read-only and tested.
- **v1-modifier:** `idiomatize` / `pattern` / `deduplicate` apply, and `apply <session_id>`. The
  corruption blocker (P0) is fixed, and apply is now guarded by context-validated diffs plus a
  post-apply `ast.parse` check that rolls back any syntactically broken result — even on repos with no
  tests. Full apply/rollback contract: [`docs/SAFETY.md`](docs/SAFETY.md). (~100 LOC removed in the same
  pass; suite at 105 tests / ~73% coverage.)

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

### P3 — Semantic safety (apply can't change behaviour or lose code) — **done**

P0–P2 closed *syntactic* corruption; these close *semantic* corruption found in an audit:

- `idiomatize` no longer rewrites a for/append loop whose value, iterable, or filter reads the
  accumulator (e.g. order-preserving dedup `if v not in u: u.append(v)`) — that silently changed
  behaviour. It also skips any file that doesn't `ast.parse` (can't safely rewrite/validate it), so one
  broken file no longer rolls back the whole batch. (`agents/idiomatizer.py`)
- `pattern singleton` writes a NEW advisory module (`singletons/…`) like every other pattern instead of
  overwriting the source file — which used to discard the original code. (`agents/pattern.py`)
- `apply` refuses any whole-file rewrite that drops a top-level/nested `def`/`class`
  (`services._def_names`) — a net for LLM rewrites and future template bugs.
- Cyclomatic complexity is word-boundary matched (McCabe, base 1); `for` is no longer double-counted as
  `or`, `editor`/`error` no longer false-positive. Drives `analyze` hotspots + `check` criticals.
  (`parse.py`)
- CLI robustness: unknown `pattern` names and non-directory paths exit `2` with a message (no traceback);
  `report` falls back cleanly when no report exists; `idiomatize` now echoes apply success/failure;
  `deduplicate` degrades to the "install the extra" message instead of crashing when `chromadb` is
  absent.

**Guarded by:** `tests/unit/test_idiomatizer.py::test_idiomatize_skips_accumulator_referencing_loop`,
`tests/unit/test_pattern_agent.py::test_singleton_pattern_writes_advisory_module_not_source`,
`tests/unit/test_apply_guard.py`, `tests/unit/test_complexity.py::test_cyclomatic_counts_for_loop_once`,
and CLI cases in `tests/e2e/test_cli_smoke.py`. Suite at 112 tests / ~73% coverage.

## Now — v1.0 (shipped & tested)

| Capability | Status | Notes |
|------------|--------|-------|
| `analyze` — tree-sitter symbols + cyclomatic & cognitive-complexity hotspots | done | Static, no LLM. Cognitive complexity is nesting-weighted, distinct from cyclomatic. |
| `idiomatize` — comprehensions (list/dict/filtered), `is None`, `len()` truthiness, `==`-chain → `in` | done | Detection, `--dry-run`, and **apply** all correct (one whole-file change per file). Optional LLM whole-file rewrite when `--model` is set. |
| `deduplicate` — embedding clustering → proposed `utils/<symbol>_dedup.py` | done (suggest-only) | Honestly labeled; does **not** remove dupes or rewrite call sites. See Near-term. |
| `pattern` — factory/strategy/observer/singleton templates | done | Named patterns rewrite/extract; auto-detect writes advisory modules. Opt-in LLM refactor when `--model` set. |
| `check` — naming, function length, per-function cyclomatic complexity | done | `critical` when CC ≥ 2× threshold. |
| Unified thresholds | done | `check` and `analyze` both read `AppConfig.complexity_thresholds`. |
| Safe apply — git checkpoint + context-validated diffs + post-apply `ast.parse` + test rollback | done | All-or-nothing; rolls back on apply error, broken syntax, or failing tests. |
| Session persistence / replay (`apply`, `sessions`, `report`) | done | JSON under `.reducto/sessions/`. |
| LiteLLM model routing (local Ollama / remote) | done | Opt-in via `--model`; tier config lives in `LLMRouter`. |
| Config: `.reducto.yaml` + `REDUCTO_*` env overrides | done | |

## Near-term (planned)

- **More idioms (heuristic tail)** — remaining patterns in `test-python-code/python/style/non_idiomatic.py`
  that need multi-line body rewrites: `enumerate` (drop `range(len(...))`), f-strings, `with`-statement
  context managers, `itertools.product`, `str.join`. Better handled holistically by the opt-in LLM rewrite
  path; only add brittle regex versions if there is clear demand.
- **Real deduplication** — rewrite call sites to import the extracted util, not just emit the module.
  Safe interim options: rewrite only when duplicates share a name, or gate behind an explicit `--rewrite`
  flag. Needs the cross-file symbol layer below.

## Mid-term

- **Cross-file impact analysis** — re-introduce an LSP/symbol-graph layer *only when a command consumes it*
  (dead-code detection, safe-rename impact, real dedup rewrite).
- **Report formats** — JSON / HTML alongside Markdown.
- **CI mode** — non-interactive `--ci` / pre-commit integration with meaningful exit codes.

## Vision (from DESIGN.md — not scheduled)

- Multi-agent orchestration (LangGraph) · pgvector persistent idiom memory · MCP server · autonomous
  PR-review mode · PDF reports · multi-language support.
