# Apply safety model

How `reducto` guarantees that applying a refactor plan is **correct and reversible**. This is the
core of the modifier lane (`idiomatize` / `pattern` / `deduplicate` apply, and `apply <session_id>`).
The implementation lives in `reducto/workspace.py`, `reducto/diff.py`, and `reducto/services.py`.

## Plan / apply split

A command never edits files directly. It produces a `RefactorPlan` — a list of `FileChange`s, each
carrying the **full** `original` and `modified` text plus a `session_id` — and `SessionStore` persists
it as JSON under `<repo>/.reducto/sessions/` *at creation time*. Applying is a separate phase
(`App.apply_plan`), so `reducto apply <session_id>` can replay a plan from disk in a later invocation.

`services._change_to_diff` converts each `FileChange` to a unified diff (splitting on `"\n"` so the
diff's line numbers line up exactly with the applier), then `Workspace.apply_changes_safe` applies the
batch.

## The apply pipeline (`Workspace.apply_changes_safe`)

Applied as one all-or-nothing transaction:

1. **Snapshot the world.** On a git repo, create a single checkpoint commit (`git_safety`). On a
   non-git target, snapshot the pre-apply contents of every target path in memory.
2. **Apply each diff** in order via `apply_diff`.
3. **Context validation** (`diff._apply_hunk`): every context (` `) and removed (`-`) line in a hunk
   must byte-match the file at that position, and may not run past end-of-file — otherwise it raises
   `DiffError`. This catches a diff that no longer matches the file (e.g. a plan replayed after the file
   drifted) instead of editing blindly.
4. **Create-over-existing guard** (`apply_diff`): a "create" diff (empty `original`, emitted for new
   advisory modules like `strategies/…` or `utils/…`) refuses to write over a file that already exists,
   so a template is never prepended into a real file.
5. **Post-apply syntax check** (`_invalid_python`): every changed `.py` must `ast.parse`; any
   `SyntaxError` fails the batch.
6. **Tests** (when `run_tests=True`): `ProjectRunner` runs `pytest -x -q` / `unittest discover` if the
   target looks like a Python project; a non-Python target reports success with no tests run.
7. **Roll back on *any* failure** (`_safe_rollback`): git targets `git reset` to the checkpoint;
   non-git targets restore the in-memory snapshot (rewriting changed files, deleting created ones). On
   success, git commit happens only when `cfg.commit_changes` is set.

## Guarantees

- **Edits land where they belong.** `idiomatize` emits one whole-file `FileChange` per file (spans
  applied in reverse), so diffs are file-relative — not the old snippet-relative diffs that landed at
  line 1 and clobbered the top of the file.
- **No invalid Python is ever left behind or committed** — the post-apply `ast.parse` rolls back, even
  on repos with no tests.
- **All-or-nothing on git *and* non-git targets** — a mid-batch failure restores earlier changes either
  way.
- **No silent file clobbering** — create diffs refuse to overwrite/merge into existing files; a stale
  diff fails loudly via context validation.
- **No path escapes** — `Workspace._resolve_path` rejects any path outside the repo root
  (`PathEscapeError`).
- **No silent code loss** — a whole-file rewrite (non-empty `original`) that would drop a
  top-level or nested `def`/`class` is refused before apply (`services._def_names`). Guards LLM
  rewrites and template bugs. `idiomatize` also skips any file that does not `ast.parse` up front —
  a file that can't be parsed can't be safely refactored or validated.

## Limits (be honest)

- Non-git rollback is **best-effort, in-memory** for the duration of one `apply_changes_safe` call; it
  does not protect against an external process mutating files concurrently. Git targets get the stronger
  guarantee.
- Test-driven rollback only trips when the target repo actually has runnable tests. The post-apply
  `ast.parse` is the backstop that covers test-less repos.
- A plan that re-targets the same new-file path twice (e.g. two same-named duplicate groups) now fails
  the batch via the create-over-existing guard rather than concatenating — safe, but it means that plan
  produces no output.
- **The git checkpoint uses `git add -A`.** On a *dirty* repo, your pre-existing uncommitted work is
  folded into the "reducto checkpoint" commit, and rollback (`git reset` to the checkpoint's parent)
  discards it from the working tree — recoverable only via `git reflog`. On a *clean* repo there is
  nothing to lose. This is exactly why mutating commands prompt before running on a dirty tree; commit
  or stash first (`--yes` skips the prompt and the safety it buys).

## Tests that lock this

| Guarantee | Test |
|-----------|------|
| Idiomatize apply lands at correct lines, docstring intact | `tests/unit/test_apply_idiomatize.py` |
| No valid `.py` becomes invalid after `idiomatize --yes` | `tests/e2e/test_cli_smoke.py::test_idiomatize_never_breaks_valid_python` |
| Context mismatch / truncation drift raises `DiffError` | `tests/unit/test_diff.py` |
| Invalid Python rolls back | `tests/unit/test_workspace.py::test_apply_changes_rolls_back_invalid_python` |
| Create-over-existing refused | `tests/unit/test_workspace.py::test_apply_diff_refuses_create_over_existing` |
| Non-git mid-batch failure restores earlier changes | `tests/unit/test_workspace.py::test_apply_changes_no_git_restores_on_failure` |
| Path escape rejected | `tests/unit/test_workspace.py::test_path_escape` |
| Rewrite dropping a `def`/`class` refused | `tests/unit/test_apply_guard.py::test_apply_plan_refuses_dropping_a_def` |
| Behaviour-changing dedup loop left alone | `tests/unit/test_idiomatizer.py::test_idiomatize_skips_accumulator_referencing_loop` |
| Singleton writes advisory module, not over source | `tests/unit/test_pattern_agent.py::test_singleton_pattern_writes_advisory_module_not_source` |
