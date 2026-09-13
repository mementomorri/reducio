# Reliability review: migration notes

This cleanup keeps the CLI commands and three usage routes: GitHub CI (primary),
PyPI, and the PyApp executable in Releases. Main-only Pages and offline dashboards
are unchanged. It deliberately removes unused and misleading Python APIs.

## Source scanning and quality checks

- Python's standard AST now supplies both symbols and metrics. Tree-sitter is
  no longer required. Supported source syntax follows the running Python version.
- Files are decoded strictly using Python encoding declarations/BOMs. Native
  proposals preserve source encoding and existing line endings; unreadable,
  invalid, symlinked and nonregular inputs produce incomplete results, not zeros.
- Incomplete analysis/check/planning exits 1. Incomplete plans cannot apply,
  including when valid files also contain useful proposals.
- Globs without a slash (for example `*.py` or `skip.py`) match basenames at any
  depth. Slashed globs are target-relative; `src/**/*.py` includes direct and nested
  files, while `src/*.py` includes direct children only. Excludes also prune matching
  directories. Hidden entries and built-in excluded directories remain excluded.
  Working-tree and Git comparison scans use the same selection rules.
- Naming and pattern checks inspect AST nodes, not comments or strings. Findings
  can change, particularly for async functions, multiline parameters, imports,
  exception bindings and pattern matching. Naming suggestions remain heuristic.

## Configuration

Unknown keys and nonpositive complexity thresholds are now errors, including nested
threshold typos. Remove `pre_approve`, `dry_run` and `report` from YAML/library
`AppConfig`; use CLI `--yes`, `--dry-run` and `--report`. Previously retired model
preferences, embedded API keys and `commit_changes` remain rejected.

## Plans, application and storage

Generated plans have `schema_version: 2`. Each `FileChange` includes
`operation: create|replace` and `encoding` (normally `utf-8`). A replacement can
empty a file or modify an existing empty file; neither operation deletes it.

Application compares **all original bytes**, then writes the proposed whole file.
Unified diffs remain previews only. Stale plans fail before editing—even when drift
is outside the preview's context. Snapshots, permission preservation, opt-in tests
and verified recovery remain; see [safety limits](SAFETY.md).

Unversioned/version-1 plans retain their old interpretation: empty `original`
means create; other originals use UTF-8 unless an encoding is recorded. Replay is
allowed only when original bytes match exactly. Regenerate plans that lost CRLF,
BOM or encoding information. Do not edit an old plan merely to bypass this check.

Sessions and reports use atomic file replacement and reject unsafe storage paths.
Timestamped report names include a unique suffix to avoid same-second collisions.
Read-only analysis/check without reports does not create storage directories.
These measures are not filesystem locking, a multi-file transaction or crash recovery.

## Python API and dependency cleanup

- Removed `reducio.diff`, `Workspace.apply_diff` and diff-string application.
  Use `App.apply_plan`; low-level `Workspace.apply_changes_safe` accepts
  `list[FileChange]` rather than `(path, unified_diff)` tuples.
- Removed regex-based symbol/block helpers from `utils.code_utils` and unused
  `PatternApplied`, `MetricsDelta`, `Report` models. Removed the unmeasured
  `maintainability_index` field; metrics v2 formulas are unchanged.
- `[embeddings]` now uses NumPy and sentence-transformers, with no Chroma database,
  persistent collections or hash-based pseudo-embeddings. Removed collection/query
  methods; use `initialize`, `embed_batch` and `find_duplicates` for run-local work.
- The embedding model remains `all-MiniLM-L6-v2` and default cosine threshold 0.85.
  Sorted representatives form deterministic groups; each member must match its
  representative. Groups are not transitive clusters and are no longer capped at
  ten results. Comparisons are batched, but worst-case work remains quadratic.
  Deduplication still only proposes utilities; it never rewrites callers.

## Release checks

Publish now calls the shared test/lint/build workflow before PyPI upload, then
downloads its verified distributions instead of rebuilding. Published-wheel identity
verification and executable smoke checks remain prerequisites for a GitHub Release.
See GitHub's [reusable workflow rules](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows).

Tests enforce **90% combined statement/branch coverage**. Local wheel smoke checks a
fresh base install, CLI/reports and mocked APIs without downloading an embedding
model. Public-PyPI identity, real model and full executable checks remain release-CI
checks. See [verification results](TEST_IMPLEMENTATION.md).
