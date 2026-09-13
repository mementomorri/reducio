# Test Rules

Functional contracts and enhancement opportunities for reducio. Each case below
states whether behavior is implemented, partial, or planned. A passing test of
one example does not establish semantic safety for arbitrary refactors.

Automated coverage and pytest layout: [TEST_IMPLEMENTATION.md](TEST_IMPLEMENTATION.md). Maintainer setup: [ONBOARDING.md](ONBOARDING.md).

## 1. Repository Analysis and Context Mapping

### Test Case: Initial Project Mapping

**Scenario**: Run the tool in a directory containing multiple modules and shared utilities.
**Status: partial.** Analysis reports function/class symbols and metrics.
Dependency/reference graphs, rich signature mapping, and entry-point detection are planned.

### Test Case: Python-Only Recognition

**Scenario**: Run the tool on a repository that contains `.py` files and other extensions (e.g. `.md`, `.json`).
**Status: implemented.** Default analysis scope processes `.py` files; invalid
Python produces explicit unavailable measurements rather than zero complexity.
Working-tree and Git scans share target-relative globs and strict Python source
decoding. Symlinked/nonregular/unreadable inputs make results incomplete. Native
plan/application tests cover CRLF, UTF-8 BOM and declared non-UTF-8 source.

## 2. Semantic Compression and Refactoring

### Test Case: Cross-File Deduplication Detection

**Scenario**: Provide two files with semantically identical logic (e.g., identical input validation blocks) but different variable names.
**Status: implemented as suggestions.** Optional embeddings identify similar
functions and propose copied utility modules. Applying writes those modules, but
does not remove originals or rewrite callers. Extraction is restricted to self-contained
top-level functions; dependency/scope exclusions are explained. Proposed Python and
source-qualified destinations are checked during planning and replay.
Mocked embedding tests cover stable representative groups, more than ten matches,
batched comparisons, malformed vectors and repeated/reordered runs without model downloads.

### Test Case: Idiomatic Transformation (Pythonic Alignment)

**Scenario**: Run the tool on a file containing verbose procedural code (e.g., a multi-line for loop used for list creation).
**Status: partial.** Existing heuristics propose comprehensions and selected
other idioms; configured models can propose broader rewrites. Behavior preservation
is incomplete; additional validated idioms are enhancement opportunities.

### Test Case: Design Pattern Injection

**Scenario**: Run the tool on a file with complex, deeply nested if-else conditionals.
**Status: partial.** Default patterns generate new advisory modules, including
singleton. A configured model can rewrite an applicable named-pattern module.
Automatic template integration into callers is planned, not implemented.

## 3. Safety Protocols and Git Integration

### Test Case: File snapshots without Git mutation

**Scenario**: Initiate a refactoring session on a project with uncommitted changes.
**Status: implemented.** Modifying commands retain dirty-tree warnings. File
snapshots preserve the actual pre-apply state; HEAD and index are not mutated.
`--yes` bypasses prompts, not warnings. Git checkpoint/commit APIs are removed.

### Test Case: Automatic Rollback on Test Failure

**Scenario**: The tool applies a refactor that causes an existing project test (e.g., pytest) to fail.
**Status: implemented for opt-in tests.** `--run-tests` runs after edits only.
Failures, launch errors and timeouts trigger scoped file recovery; restoration
is verified, and failures report retained backup paths. No atomic/crash guarantee.

### Test Case: Human-in-the-Loop Approval

**Scenario**: User requests a compression operation.
**Status: partial.** Approval is per nonempty plan and can be bypassed with
`--yes`. CLI output includes session IDs and dry-run report paths. Reports, session
display, and pre-apply output include unified diffs and provenance; side-by-side
display remains optional future work. Empty/incomplete plans are not applied.

### Test Case: Non-Destructive Apply

**Scenario**: Apply a plan that would land an edit somewhere other than the top of a file, that no longer matches the on-disk file, that yields invalid Python, or that creates a module whose path already exists.
**Status: partial.** File-relative diffs validate context, create diffs reject
existing files, and syntax failures trigger recovery on handled paths. Reliable
atomic recovery on all Git/non-Git paths is not implemented. See [SAFETY.md](SAFETY.md).

## 4. Model Orchestration and Performance

### Test Case: Model Provider Switching

**Scenario**: Explicitly select an OpenAI/Anthropic-compatible API and model.
**Status: implemented (mocked API contracts).** CLI settings override environment,
selected YAML, then defaults. HTTP support is optional and lazy. Missing credentials,
timeouts, refusals and malformed replies fail planning unless fallback is explicit.
No automatic model discovery, tiers, retries or provider switching are supported.
Live provider availability and model-specific compatibility are not certified.

### Test Case: Functional Parity Validation (Pass@1)

**Scenario**: Apply a refactor to a core business logic function.
**Status: partial.** Explicit target runner selection and passed/failed/error/not-run
reporting are implemented. Narrow heuristic prerequisites have regression coverage;
passing tests still does not prove equivalence, especially for model rewrites.

## 5. Reporting and Metrics

### Test Case: Complexity Reduction Report

**Scenario**: Execute the tool with the --report flag.
**Status: implemented.** `analyze` and `compare` produce Markdown/JSON/HTML with
shared AST metrics. Apply sessions produce Markdown/JSON whole-file metrics and
matched-function deltas, with attempted versus retained state after recovery.
Unavailable measurements are not zeros. Cognitive is a custom reducio score.

### Test Case: Duplicate Removal Statistics

**Scenario**: Run a deduplication session across a large project.
**Status: planned.** Deduplication does not remove duplicate blocks today, so no
removal/savings claim is justified. Real extraction and measured impact require
caller/import rewriting and validation first.

## 6. User-Flow Integration

### Test Case: CLI Flow Continuity

**Scenario**: Navigate to a project folder and run `reducio deduplicate .`.
**Status: partial.** Scan → persist proposal → approval (or `--yes`) → apply
advisory modules → syntax/metrics validation and opt-in tests → result report.
There are no automatic commits or Git checkpoints. Failed returned
applications exit 1 with a reason; successful applications and ordinary declined
approval exit 0. Input errors exit 2. Remaining workflow safety limits are above.
