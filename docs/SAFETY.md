# Apply safety model

The checks and known limits when applying a refactor plan. **Automatic modification
is not production-safe, behavior-preserving, or reliably reversible.** This is the
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

The implementation attempts a guarded batch, not a guaranteed atomic transaction:

1. **Checkpoint/snapshot.** On a git repo, create a checkpoint commit staging all files (`git_safety`). On a
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
7. **Attempt rollback on handled failures** (`_safe_rollback`): Git resets to the
   checkpoint's **parent**, not the pre-apply checkpoint contents. Non-git targets
   attempt to restore the in-memory snapshot. Exceptions can bypass recovery and
   suppressed rollback errors can still be reported as success. On success, an
   additional result commit is optional; the Git checkpoint already created a commit.

## Implemented safeguards (not semantic guarantees)

- **Edits land where they belong.** `idiomatize` emits one whole-file `FileChange` per file (spans
  applied in reverse), so diffs are file-relative — not the old snippet-relative diffs that landed at
  line 1 and clobbered the top of the file.
- **Syntax validation** — post-apply `ast.parse` detects invalid changed Python
  and requests rollback on handled failures, including targets without tests.
  Successful restoration is not guaranteed.
- **No silent file clobbering** — create diffs refuse to overwrite/merge into existing files; a stale
  diff fails loudly via context validation.
- **Workspace path containment** — `Workspace._resolve_path` rejects resolved paths
  outside its root. This does not validate session IDs (TODO 15).
- **Definition-name guard** — a whole-file rewrite (non-empty `original`) that would drop a
  top-level or nested `def`/`class` is refused before apply (`services._def_names`). Guards LLM
  rewrites and template bugs, but does not detect arbitrary code loss or behavior changes.
  `idiomatize` also skips any file that does not `ast.parse` up front —
  a file that can't be parsed can't be safely refactored or validated.

## Limits (be honest)

- Git and non-git recovery are **best-effort**; neither guarantees restoration.
  In-memory snapshots last only for one operation and do not protect against concurrent changes.
- Test-driven rollback only trips when the target repo actually has runnable tests. The post-apply
  `ast.parse` detects syntax errors, not behavioral equivalence. Runner selection
  can fail to run intended tests or report success when none ran.
- A plan that re-targets the same new-file path twice (e.g. two same-named duplicate groups) now fails
  the batch via the create-over-existing guard rather than concatenating; partial
  writes may remain if recovery fails.
- **The git checkpoint uses `git add -A`.** On a *dirty* repo, your pre-existing uncommitted work is
  folded into the "reducto checkpoint" commit, and rollback (`git reset` to the checkpoint's parent)
  discards it from the working tree. The checkpoint may be recoverable through
  `git reflog`, but staged/unstaged distinctions are not preserved. Clean targets
  still face exceptional-recovery and newly-created-file defects. Modifying commands,
  including saved-plan replay, warn on dirty Git roots; `--yes` bypasses prompts,
  not warnings. This warning does not repair rollback.
- Current idioms can alter strings/comments, lose accumulator state, and change
  evaluation order. LLM output has the same review requirement. These and recovery
  defects remain release blockers in [TODO 19–24](../TODO.md).

Use an independent backup and disposable checkout, inspect original/modified
session JSON, and run behavior tests independently before adopting a proposal.
CLI apply failures now exit 1 with a reason; success still does not prove safety.

## Tests of specific safeguards

These cover selected inputs, not universal guarantees or all recovery paths.

| Checked case | Test |
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
