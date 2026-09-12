# Implementation assessment

## Section 3 update — 2026-09-12

Items 19–25 are implemented locally: conservative AST/token-aware idioms,
durable scoped file snapshots (no Git writes), exception-safe verified recovery,
opt-in explicit target tests, and whole-affected-file apply metrics/reports.
The maintainer also confirmed successful PyPI configuration and publication.
See [SAFETY.md](SAFETY.md) for the supported subset, configuration migration and
remaining limits; [TODO.md](../TODO.md) tracks follow-up work.

Final local verification: **419 passed, no expected failures, 92.24% coverage**.
Lint, formatting, types, wheel/sdist build and installed-wheel CLI/report smoke
pass; tracked fixtures are unchanged. See [TEST_IMPLEMENTATION.md](TEST_IMPLEMENTATION.md).

The audit and verification snapshots below are **historical**. In particular,
their regex/checkpoint/default-test and LOC-only report findings are superseded
by this implementation, not claims about the current code.

Originally reviewed **2026-09-10**, against `main` at **`1e79b7b`** (`feat(cli): verbose
listings and check reports`). Package version: **1.0.0**, Python **3.14+**.
Canonical repository, confirmed by the maintainer: **`mementomorri/reducio`**.

Updated **2026-09-11** for section 1 implementation on top of `2ca053b`.
This assessment includes current implementation updates and the original audit.
The actionable backlog is
[TODO.md](../TODO.md), ordered from small corrections to larger decisions. Its
order reflects effort; the release blockers below reflect severity.

## Implementation update — CLI contracts and documentation

**Section 2 follow-up:** target-local reports, unified previews, safe session paths,
explicit planning failures/provenance, bounded advisory preflight, and subprocess
coverage are now implemented. Installation is limited to GitHub CI, the
`reducio` PyPI distribution, and PyApp executables; CLI/import stay `reducio`.
First public publication/Trusted Publishing setup remain operational follow-ups.
The snapshot below describes the earlier section 1 work; current verification is
recorded in [TEST_IMPLEMENTATION.md](TEST_IMPLEMENTATION.md): **328 passed,
5 strict expected failures, 91.43% coverage**; lint/type/build checks and
installed-wheel CLI/report smoke passed. No public publication or PyApp build
was run locally; section 3 safety defects remain unresolved.

TODO section 1 is implemented locally: ANSI-resilient help tests, canonical active
links and local origin, truthful plan/session/report output, nonzero failed-apply
exits, saved-plan dirty warnings, and consistent directory/configuration validation.
Explicit CLI model/verbosity/preference overrides now win over environment, selected
YAML, and defaults; services preserve resolved settings. `--no-verbose` disables
details independently of `--quiet`. Invalid inputs exit 2 without configuration dumps.

Safety/architecture/user/onboarding/testing docs distinguish actual safeguards
from planned capabilities. The later section 2 update removes the Bash installer
and container support. No rollback or rewriting engine was changed. Items 19–24
remain safety blockers.

Local verification: **266 tests passed, 85.15% coverage**; CLI coverage **83%**,
configuration **100%**. Ruff, Black, mypy, and wheel/sdist build passed; tracked
fixtures are unchanged. Details: [TEST_IMPLEMENTATION.md](TEST_IMPLEMENTATION.md).
Earlier remote inspection found Analysis/Pages and Installation successful but
two colored-help test failures in CI at `c467841`; the local fix does not imply a
new remote run succeeded. No push or remote workflow rerun was performed.

## Earlier implementation update — metrics and CI reporting (historical)

Implemented locally after the baseline commit:

- Mandatory **metrics v2**: AST decisions, independent functions/methods, no class
  double-counting, uncapped hotspot counts, physical LOC, explicit parse failures.
  `analyze`, `check`, and `compare` share these rules; cognitive is explicitly a
  custom Reducio score, not Sonar-compatible. See [METRICS.md](METRICS.md).
- **`compare`** reads committed changed-file blobs without checkout or target
  execution. It matches qualified function names and Git-detected file renames;
  additions/removals are separate from matched-function deltas.
- **Markdown, JSON, and offline HTML dashboards**, with `--format` and
  `--output-dir` on analysis/comparison. Full data is retained; display lists are
  capped at 20. Legacy apply-session reports still lack complexity deltas.
- **Separate CI jobs**: source overview on pushes/manual runs, merge-base-to-head
  comparison on PRs. Summary tables and distinct downloadable artifacts; available
  reports upload after failures. Complexity verdicts are informational. The old
  log-grep parser guard is replaced by JSON validation with regression tests.
- Fixture parse failures are explicit and tested; tracked fixtures are unchanged.
  The roadmap now distinguishes shipped features from incomplete modifier safety.

Historical local verification: **169 tests passed, 80.88% coverage**; Ruff, Black, mypy, and
wheel/sdist build passed. The metric engine reached 100% statement coverage.
Browser inspection rendered all three overview and four comparison charts with
**no page errors or external requests**. See [TEST_IMPLEMENTATION.md](TEST_IMPLEMENTATION.md)
for test commands. Remote GitHub execution has not been run from this checkout.
Usage and result access: [CI.md](CI.md). Existing local edits to `SAFETY.md` were
preserved; no modifying refactor was run on this checkout.

## Verdict

**The v1 feature set exists, but automatic modification is not production-safe.**
Static analysis, quality checks, planning, session persistence, and Markdown
reports work. Several earlier corruption defects have been fixed. However, current
idiom rewrites can still change program output, and rollback does not reliably
preserve the state that existed immediately before application.

The previous roadmap's claims of provable correctness and complete semantic safety
were stronger than the implementation supports and have been corrected. Syntax validation,
definition-name checks, and passing tests are useful safeguards; they do not prove
that every proposed transformation preserves behavior.

## Original verified baseline and scope (historical)

The following checks ran locally during this review, using the existing Python
3.14.7 virtual environment at the commit above:

| Check | Result |
| --- | --- |
| `pytest -q` | 120 passed; 72.16% coverage; 60% coverage gate passed |
| `ruff check reducio/ --no-cache` | Passed |
| `black --check reducio/` | Passed; 27 source files unchanged |
| `mypy reducio/ --ignore-missing-imports` | Passed; notes about unchecked untyped function bodies |
| `reducio version` | `reducio 1.0.0` |
| `reducio analyze reducio/ -v` | 27 files, 215 symbols, 20 reported hotspots |
| `reducio check reducio/` | 58 issues: 0 critical, 51 warning, 7 info |

The counts above came from the old metric engine. They are not comparable to v2;
both sides of a new revision comparison are remeasured with the current engine.

Additional probes compared original and rewritten functions in memory, supplied
stubbed failed apply results to the real CLI, and inspected session path
resolution without accessing files outside session storage. No refactor was
applied to this checkout. Remote CI, published packages, and live LLM-provider
behavior were not independently verified. That original review was documentation-only;
the implementation update above records subsequent application changes.

## What currently works

| Capability | Actual behavior and limits |
| --- | --- |
| Analysis and quality checks | AST symbol extraction, defined syntax-aware function metrics, naming and function-length checks. Explicit unavailable measurements. No LLM required. |
| Revision comparison | Complete changed-file function metrics at two exact commits; deltas and unmatched additions/removals. No target execution or checkout. |
| Idiom planning | Produces one whole-file change per file. Skips invalid Python and some accumulator-dependent loops. Remaining unsafe cases are listed below. |
| Deduplication | Embedding similarity proposes shared utility modules. It does not remove duplicates or rewrite callers. Requires the optional embeddings dependencies for useful results. |
| Design patterns | Default factory, strategy, observer, and singleton paths produce advisory modules. They do not integrate those templates into existing callers. |
| Optional LLM rewrites | A configured model enables whole-module rewriting for idiomatize and applicable named patterns. `pattern` currently takes model selection through configuration/environment, not a `--model` CLI flag. |
| Persistence and reports | Plans are saved as JSON and can be replayed. Analysis/comparison support Markdown/JSON/offline HTML; quality, dry-run, and apply remain Markdown. Plan previews and legacy report locations need improvement. |
| Apply safeguards | Context-validated diffs, create-over-existing rejection, syntax checks, definition-name checks, and rollback attempts on handled failures exist. They have the limitations below. |

Analysis and dry-run modes leave target source code unchanged, but can create
`.reducio` directories, reports, and saved plans. They are not strictly free of
filesystem writes.

The architecture remains one Python process: Typer CLI → `App` services →
workspace and specialized agents. See [ARCHITECTURE.md](ARCHITECTURE.md).

## Earlier findings that are fixed

These should not be carried forward as unresolved defects from the earlier
assessment:

| Earlier defect | Current implementation |
| --- | --- |
| Snippet-relative idiom diffs corrupt the beginning of a file | One full-file change is emitted per file; diff context/removals are validated. |
| Pattern singleton replaces the source module | Singleton now writes a new advisory module, like the other default patterns. |
| Some list rewrites read their own accumulator | Simple and filtered list rules now reject explicit accumulator references in the iterable/value/filter. This is a partial semantic fix, not a general proof. |
| Missing `chromadb` crashes during module import | Import is deferred and missing optional imports follow the unavailable-embeddings path. |
| Keywords in literals/comments affect complexity | AST metrics v2 ignore non-code text, superseding the earlier word-boundary fix. |
| Unknown pattern names and file targets cause poor CLI behavior | Main commands validate repository directories; unknown pattern names exit 2. Session commands still need consistent validation. |
| Missing reports produce an unhandled traceback | Report lookup handles missing reports and considers all generated report types for latest-report lookup. |
| Missing/misleading CLI application outcomes | All four modifying commands now print actual returned success/failure; failed application exits 1. Plans say proposed, not applied. |
| Saved-plan replay omits dirty-tree warning | Replay now uses the same warning and approval behavior; rollback itself remains unsafe. |
| Default flags overwrite configuration | Explicit CLI settings now win over environment/file defaults; omitted settings and resolved service configuration are preserved. |
| Missing/malformed config or invalid session target | Clear input errors exit 2; session targets are validated before storage creation. |
| Colored help breaks flag assertions in CI | Help tests strip ANSI styling and exercise both normal and forced-color output. |
| Repository/usage docs are inconsistent | Active links and local origin are canonical; flags and acceptance criteria reflect implemented versus planned behavior. |
| Apply report LOC values are always zero | Successful application now populates before/after LOC totals. Complexity deltas are still absent. |

The original suite had 120 tests; the 105/112-test figures in older documents
describe earlier snapshots. Additional metric/report/comparison tests now exist.

## Release blockers

### 1. Idiom rewrites still change behavior

**Reproduced in memory** using the current idiomatizer:

| Original operation | Original result | Result after rewriting |
| --- | --- | --- |
| `return "x == None"` | `"x == None"` | `"x is None"` |
| Start with `out = [99]`, then append each value from `range(2)` | `[99, 0, 1]` | `[0, 1]` |
| Start with `d = {}`, then assign `d[x] = len(d)` for each value in `range(3)` | `{0: 0, 1: 1, 2: 2}` | `{0: 0, 1: 0, 2: 0}` |

`_compare_to_none` runs regex substitutions across literal text. The list rule
replaces accumulation with a new assignment without proving the accumulator is
fresh and unaliased. The dictionary rule does not reject reads from the dictionary
being built. All three examples remain valid Python and retain their function
names, so the syntax and definition-name guards cannot detect these failures.
Target tests could detect them if those behaviors are covered.

**Additional risks identified by code inspection:** equality-chain conversion
can replace short-circuit evaluation with eager tuple construction; truthiness
and `len` comparisons can differ for custom objects; overloaded equality can
make `== None` differ from `is None`. Loop-variable scope, aliases, and complete
loop bodies also need explicit handling. These broader cases require focused
behavior tests before declaring the rules safe.

Sources: [idiomatizer.py](../reducio/agents/idiomatizer.py),
[apply guard](../reducio/services.py). Backlog: **TODO 19–21, 26**.

### 2. Git rollback restores the wrong baseline for dirty targets

**Confirmed in the implementation and the existing passing regression test:**
checkpoint creation stages all files and commits them. Rollback resets to that
checkpoint's **parent**, not to the pre-apply contents stored in the checkpoint.
Pre-existing uncommitted work is therefore discarded from the working tree on
rollback, although the checkpoint may remain recoverable through Git's reflog.

The existing test starts from `x = 1`, changes it to `x = 2` before checkpointing,
and expects rollback to restore `x = 1`. It currently locks in the undesirable
behavior. Saved-plan `apply` now warns on dirty Git roots like the other modifying
commands, but that does not fix rollback.

Recovery needs to preserve staged, unstaged, and untracked user work. Tests must
also cover newly created advisory files and failed restoration. The choice of
checkpoint, stash, or snapshot mechanism remains an implementation decision.

Sources: [git_safety.py](../reducio/git_safety.py),
[workspace.py](../reducio/workspace.py), [test_git.py](../tests/unit/test_git.py),
[cli.py](../reducio/cli.py). Backlog: **TODO 22**; warning consistency (09) is fixed.

### 3. Exceptions can bypass recovery, and rollback status is optimistic

**Identified by code inspection:** failures returned by the test runner trigger
rollback, but exceptions while launching tests, subprocess timeouts, and some
post-apply validation errors can escape after writes. `_safe_rollback` suppresses
`GitError`; callers derive `rolled_back=True` from having a checkpoint/snapshot,
not from confirming successful restoration.

The entire post-write validation/test phase needs recovery handling, and reported
rollback status must reflect what actually happened. The runner also uses bare
`python` and can report test success when no tests ran; interpreter selection and
passed/failed/not-run outcomes need an explicit contract.

Sources: [workspace.py](../reducio/workspace.py),
[runner.py](../reducio/runner.py). Backlog: **TODO 23–24**.

## Other current defects and inconsistencies

| Finding | Evidence and impact | TODO |
| --- | --- | --- |
| Session path isolation — fixed locally | IDs/containment are validated before cache or file access, symlinks rejected, filename/metadata identities checked. Unsafe listings are skipped with warnings. This is not a concurrent hostile-filesystem sandbox. | 15 |
| Remaining configuration/CI policies | Precedence and validation are fixed; configurable finding gates and a broader noninteractive approval policy remain undecided. | 28 |
| Report roots — fixed locally | Default reports and sessions share the target's `.reducio`. Explicit output directories remain caller-relative; report lookup accepts `-C`. | 13 |
| Plan previews — fixed locally | Dry-run Markdown, session display, and pre-apply output include unified diffs, diagnostics, and provenance, including with `--yes`. | 14 |
| Advisory preflight — bounded fix implemented | Only self-contained top-level functions are extracted. Generated paths are source-qualified; syntax and destination conflicts are checked before application and replay. This does not prove semantic equivalence. | 18 |
| Silent planning failures — fixed locally | Parser/required embeddings and selected-model failures make plans incomplete. Explicit `--allow-fallback` permits logged heuristic/template fallback. Incomplete plans cannot apply. | 17 |
| Distribution identity — fixed locally, first publication pending | The maintainer chose `reducio`; CLI/import stay `reducio`. Its PyPI endpoint returned 404 on 2026-09-11 (not a reservation guarantee). Configure Trusted Publishing before the first release. Only CI, PyPI, and Releases executables remain supported routes. | 12 |
| Task-based model routing is not operational in the normal agent path | A configured model enables rewriting and bypasses tier selection. Tier-selection unit tests do not demonstrate task-based routing in an actual workflow. | 27 |

The repository identity is a confirmed maintainer choice, not inferred from a
remote lookup. The local origin URL now matches `mementomorri/reducio`; no hosted
repository settings were changed. The package
version and locally available tags alone do not establish what has been published.

## Test coverage and documentation gaps

The CLI has subprocess smoke tests and in-process analysis/comparison and command
contract tests. Coverage measures the latter, but not subprocesses. Several older tests
assert exit status or syntax
without asserting successful application or preserved runtime behavior; the
reproductions above demonstrate why those distinctions matter.

Approval-decline, failed-apply exit, and dirty-warning tests now exist. Still add
behavior comparisons for rewritten functions, dirty-state preservation, and runner/recovery exceptions.
Measure CLI execution either through subprocess coverage or focused `CliRunner`
tests. Keep live provider/model integration results distinct from mocked tests.

[TEST_RULES.md](TEST_RULES.md) now explicitly separates implemented behavior from goals:
dependency mapping, side-by-side previews, before/after complexity deltas,
duplicate-removal statistics, and task-based routing are not all implemented.
Default pattern templates are advisory modules. Richer analysis/comparison reports
are now implemented; apply preview improvements remain planned.
Backlog: **TODO 16** (remaining coverage/behavior work).

## Roadmap position and next steps

The implementation has reached the **v1 feature milestone**, but the modifier's
**safety milestone remains incomplete**. Keep the fixes already delivered under
P0–P3 recorded as completed work; revise their broad safety conclusions to account
for the remaining blockers rather than describing those individual fixes as absent.

Recommended sequencing:

1. Section 1 links, documentation, input validation, configuration precedence,
   and CLI result/exit fixes are complete locally. Push/review CI separately.
2. Resolve behavior-changing idioms and reliable recovery before promoting
   automatic modification as production-safe. Add tests for the concrete failures.
3. Improve plan review, legacy report locations, and target test
   execution. Shared metric correctness and revision reporting are implemented.
4. Decide model-routing policy and the scope of real deduplication. Caller
   rewriting requires cross-file dependency/reference handling. Pre-commit
   integration and broader orchestration remain subsequent features.

Unused-code cleanup and replacing parsing, Git, or formatting libraries are
optional design work. They should not be mistaken for fixes to the correctness
defects above. The detailed tasks and unresolved design choices remain in
[TODO.md](../TODO.md), especially **26–30**.
