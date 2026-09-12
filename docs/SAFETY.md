# Apply safety model

Application edits files only. It never stages, commits, resets, or stashes Git state.
Review proposals before applying; syntax checks and passing tests do not prove
behavioral equivalence. Model-generated changes remain unverified proposals.

Nonempty application in CI or with non-TTY stdin requires an explicit CLI
`--yes`; configuration cannot grant unattended approval. Dry runs and empty
plans do not prompt. `--yes` does not bypass validation or suppress dirty warnings.
Model planning sends source to the configured API even in dry-run mode; see
[API setup and privacy](LLM.md). Saved-plan replay makes no model request.

## Pipeline

1. Validate plan completeness, paths, syntax, definition names, destination
   collisions, and every diff's context before any target write.
2. Measure whole affected Python files with the shared AST metrics v2 engine.
3. Save pre-apply bytes, permissions and existence in
   `<target>/.reducio/recovery/<attempt-id>/`, with a JSON manifest and binary backups.
4. Replace each file atomically, preserving its permissions; validate syntax and metrics.
5. Only with `--run-tests`, execute the target's tests **after edits**.
6. On write, validation, requested-test failure, exception or timeout, restore
   affected files and verify bytes/permissions. Remove newly created files and
   only empty directories created by this operation.
7. Report actual test and recovery status, backup location, and affected-file
   before/attempted/retained measurements. Git history and staging are untouched.

The same path handles Git repositories, subdirectories, worktrees, unborn
repositories, and non-Git directories. Symlinks, hardlinked targets, escaped paths,
Git metadata and reducio's own storage are rejected as modification targets.
Existing files cannot be overwritten by a create-file proposal.

## Opt-in target tests

All four modifying commands support `--run-tests`, `--report`, and `--output-dir`:

```bash
reducio idiomatize . --dry-run
reducio apply <session-id> --run-tests --report
```

Without `--run-tests`, the outcome is `not_run`, never “tests passed.”
`App.apply_plan` and `Workspace.apply_changes_safe` also default to no tests.

Configure the target runner in the selected YAML file:

```yaml
test_runner: pytest          # pytest (default) or unittest
test_python: .venv/bin/python
test_timeout_seconds: 300
# Optional override: an argv list, not a shell string.
# test_command: ["uv", "run", "pytest", "-q"]
```

Resolution: explicit `test_command` > configured `test_python` > target-local
`.venv/bin/python` (Windows: `.venv/Scripts/python.exe`).
There is no implicit fallback to the tool's interpreter or bare `python`.
Relative executable paths resolve from the target; explicitly named commands
resolve through PATH. Commands run with `shell=False` and target working directory.
No dependency installation is performed.

Missing runner/interpreter, timeout, or built-in pytest/unittest discovering zero
tests fails requested validation and triggers recovery. Explicit custom commands
use their exit status; test counts may be unknown. Commands and tests execute
arbitrary target code: this is **not a sandbox**, and their unrelated side effects
are not undone. Use a trusted command and isolated checkout.

## Recovery and reports

Statuses are `test_status: not_run|passed|failed|error` and
`recovery_status: not_needed|restored|failed`. `tests_passed` is only a compatibility
projection of `test_status == passed`. Recovery success means verification actually
succeeded; failed restoration reports errors and the retained backup location.

Backups are retained on successful, restored, failed, and interrupted attempts.
Inspect `manifest.json` to identify original paths and numbered binary backups.
If recovery fails, stop editing, preserve that directory, and compare the backup
with current files before restoring manually. Concurrent changes detected by
content/permission checks are not overwritten. Backups may contain sensitive code;
keep them private and remove reviewed old attempt directories yourself.

This is **not a multi-file atomic transaction or crash-proof recovery system**.
Abrupt termination can leave partial edits; there is no automatic crash-resume.
Checks reduce common races but do not provide filesystem locking against hostile
concurrent mutation. Ownership, timestamps, ACLs and extended attributes are not
snapshotted; byte contents, existence and permission bits are.

`--report` writes Markdown plus structured JSON for success and application failure.
Metrics cover whole affected Python files, with matched-function deltas and
separate additions/removals. Attempted state is measured after successful syntax
validation; unavailable measurements are explicitly absent, not zero. Retained
state reflects files left after recovery. These reports do not add an HTML dashboard.
A report-write failure exits nonzero and identifies whether changes were applied;
it does not roll back an otherwise successful operation.

## Supported heuristic idioms

AST node selection and token-aware source slices preserve strings, comments and
unaffected formatting. Overlapping comments cause the candidate to be skipped.

Comprehensions require an immediately preceding fresh empty local list/dictionary,
a complete supported loop body, a small nonempty literal iterable or unshadowed
builtin range, and closed built-in expressions. Accumulator references, aliases,
escaping loop variables, closures, global/nonlocal state, extra statements and
exception contexts are rejected. Accumulator and loop-variable names must
not reuse parameters or earlier bindings, avoiding changes to finalizer timing.
None comparisons, truthiness and membership
rewrites require locally established built-in values; unknown/overloaded values
and side-effecting expressions are skipped. Truthiness is restricted to supported
single-evaluation conditions, not while-loop invariants.

The supported subset is deliberately narrow; there is no unsafe heuristic override.
Reflection/tracing, monkeypatched builtins and resource-exhaustion equivalence are
not guaranteed. Wider patterns are enhancement opportunities, not current support.
Saved plans remain reviewable proposals; old/model plans are not retrospectively
certified by the new heuristic checks.

## Migration

Remove `commit_changes` from configuration: even `false` now raises a clear
configuration error. Git checkpoint/rollback/commit APIs are removed.
Commit reviewed changes manually. Previous report consumers must handle absent
metrics and explicit test/recovery statuses.

Regression coverage: `tests/unit/test_section3_safety.py`,
`test_known_safety_gaps.py`, `test_git.py`, `test_workspace.py`, and CLI tests.
