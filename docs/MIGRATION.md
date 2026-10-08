# Migration notes

Newest first. All releases keep the three usage routes: GitHub CI (primary), PyPI,
and the PyApp executable in Releases.

## Local-only model planning (2026-10)

- **Breaking:** `idiomatize` and named `pattern` proposals refuse non-loopback API
  hosts — including the default OpenAI/Anthropic URLs — until you consent with
  `--allow-remote`, `REDUCIO_ALLOW_REMOTE=1` or `allow_remote: true`. Without it the
  plan is incomplete (exit 1) and no request is made. Loopback endpoints are unchanged.
- Model planning prints a disclosure line on stderr, even with `--quiet`.
- `PlanningProvenance` gains optional `endpoint`, `prompt_bytes` and
  `prompt_sha256`; older saved plans load unchanged.

## Deduplication and hotspot policy (2026-10)

- **Hotspots** now include functions whose cognitive score reaches
  `complexity_thresholds.cognitive_complexity` (default 15), not only CC; `check`
  reports one `high_complexity_function` finding naming every crossed metric. Raise
  `cognitive_complexity` to restore CC-only selection.
- `deduplicate` also suggests near-miss clones (≥90% similar normalized AST).
- `deduplicate --rewrite` (opt-in) replaces identical copies with imports.
- Suggestions (without `--rewrite`) now include functions that use module names
  (imports, globals); the needed names are listed in the proposed module and
  description. `--rewrite` still only moves self-contained functions. Skip
  diagnostics are one summary per file and reason instead of one per function.
- Functions reading module dunders such as `__name__` are no longer proposed as
  shared utilities, nor are functions relying on a `global`-rebound builtin.

## Code-reduction follow-up (2026-10)

- **Embeddings removed.** `deduplicate` groups exact structural clones by AST
  fingerprint (identifiers, literals and docstrings abstracted; 2+ statements) with
  the standard library. The `[embeddings]` extra, `reducio.embeddings`,
  `EmbeddingService`, `CodeBlock`, `DuplicateGroup`, `AnalyzeResult.duplicates`
  and `DeduplicateRequest.similarity_threshold` are gone; no model is downloaded.
  Near-miss clones later returned as suggestions (see "Deduplication and hotspot policy" above).
- **Heuristic idioms removed.** `reducio.idioms` is deleted and `idiomatize` is
  model-only: it exits 2 without `--llm-api`/`--model`. Its `--allow-fallback` flag
  and `IdiomatizeRequest.allow_fallback` are removed (`pattern --allow-fallback`
  remains for templates).
- **No async API.** `App`, agent and `LLMClient.complete` methods are plain
  functions (drop `await`/`asyncio.run`). `llm_timeout_seconds` is now httpx's
  per-phase timeout, not a total deadline. `pytest-asyncio` is no longer a dev dependency.
- **GitPython removed.** Dirty-tree checks run `git status --porcelain`;
  `reducio.git_safety`/`GitSafety` are gone (`reducio.compare.worktree_clean`).
- **Default excludes are explicit.** `venv`, `node_modules`, `__pycache__`, `dist`,
  `build` and `target` moved from a hidden list into the `exclude_patterns` default,
  so they can be overridden. **A configured `exclude_patterns` replaces the whole
  default list — re-add these names if your config sets its own list.**
- **Repeated names pair in order.** `compare`/`history` match same-name definitions
  (property getter/setter, overloads) in source order when both sides have the same
  count, instead of reporting them as removed + added (and new hotspots).
- **Quality check:** plain imports (`import os`) are no longer naming findings;
  explicit `as` aliases still are.
- **Storage:** reducio writes `.reducio/.gitignore` (`*`) so plans, reports and
  recovery backups never dirty the tree or get committed.
- **Removed unused APIs:** `Workspace.read_file/get_symbols/get_complexity/run_tests/
  is_git_clean`, `PathEscapeError`, `parse.get_symbols`, `ParserError`,
  `utils.calculate_complexity`, `metrics.measure_functions`,
  `SessionStore.delete_session/get_session_info/clear_cache`, `SessionInfo.to_dict`,
  `Reporter.generate_baseline` (use `visual_report.write_reports`),
  `Symbol.signature/references`. Agents now need a workspace or a session store.
- **Version:** `pyproject.toml` reads the version from `reducio/__init__.py`
  (hatch dynamic version); release CI stamps only that file.

## Renamed from `reducto`

Use `reducio` instead of `reducto` in commands/imports and `REDUCIO_*` instead of
`REDUCTO_*` environment variables. Configuration is now `.reducio.yaml`, and
reports/sessions use `.reducio/`. Existing `.reducto` files are left untouched;
copy any configuration or sessions you want to retain. There are no legacy
command/import aliases. The repository and Pages links use `mementomorri/reducio`
and `https://mementomorri.github.io/reducio/`.

## Model APIs

Removed `LLMRouter`, `ModelTier`, LiteLLM and tier/discovery logic. Library callers
use `LLMClient(AppConfig(llm_api="openai", model="...")).complete(...)`. Remove
retired `prefer_local`, `prefer_remote`, `model_tiers`, `tier`, `REDUCIO_PREFER_LOCAL`
and `REDUCIO_PREFER_REMOTE`: these fail configuration validation. Model IDs are passed
unchanged. Existing saved plans replay without an API request.

## Commit settings and Git checkpoints

Remove `commit_changes` from configuration: even `false` raises a clear error.
Git checkpoint/rollback/commit APIs are removed; commit reviewed changes manually.
Report consumers must handle absent metrics and explicit test/recovery statuses.

## Reliability review (2026-09)

This cleanup removed unused and misleading Python APIs.

## Source scanning and quality checks

- Python's standard AST supplies both symbols and metrics. Supported source
  syntax follows the running Python version.
- Files are decoded strictly using Python encoding declarations/BOMs. Native
  proposals preserve source encoding and existing line endings; unreadable,
  invalid, symlinked and nonregular inputs produce incomplete results, not zeros.
- Incomplete analysis/check/planning exits 1. Incomplete plans cannot apply,
  including when valid files also contain useful proposals.
- Globs without a slash (for example `*.py` or `skip.py`) match basenames at any
  depth. Slashed globs are target-relative; `src/**/*.py` includes direct and nested
  files, while `src/*.py` includes direct children only. Excludes also prune matching
  directories. Hidden entries remain excluded.
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

## Release checks

Publish now calls the shared test/lint/build workflow before PyPI upload, then
downloads its verified distributions instead of rebuilding. Published-wheel identity
verification and executable smoke checks remain prerequisites for a GitHub Release.
See GitHub's [reusable workflow rules](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows).

Tests enforce **90% combined statement/branch coverage**. Local wheel smoke checks a
fresh base install, CLI/reports and mocked APIs. Public-PyPI identity and full
executable checks remain release-CI checks. See [verification results](TEST_IMPLEMENTATION.md).
