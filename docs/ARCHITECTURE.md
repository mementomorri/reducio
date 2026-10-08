# reducio Architecture

Python 3.14+ CLI for semantic compression of **Python source code**. One process: Typer CLI, in-process `Workspace`, optional model API client.

## Overview

```
User
  → reducio.cli (Typer)
       → reducio.services.App
            → Workspace (repo walk *.py, whole-file apply, recovery, tests)
            → Agents (analyze, deduplicate, idiomatize, pattern, check)
            → LLMClient (optional explicit compatible API)
            → SessionStore (.reducio/sessions)
            → Reporter / visual_report (.reducio/*.md|json|html)
```

## Package map

| Module | Role |
|--------|------|
| `cli.py` | Commands, git dirty check, shared options, session subcommands |
| `services.py` | `App`: orchestrates agents and guarded apply |
| `workspace.py` | File listing, exact-content application, opt-in tests |
| `repo.py` | Walk repo; include `*.py` by default; `detect_language` → Python or unknown |
| `parse.py` | Python AST symbols; compatibility `get_complexity` import |
| `metrics.py`, `analysis.py` | Shared AST metrics and complete function analysis |
| `compare.py` | Git helper (`_git`, batched blobs, `worktree_clean`), exact/merge-base snapshots or working files |
| `history.py` | First-parent snapshots, batched Git blobs, run-local metric reuse and source-root aliases |
| `history_report.py`, `history_view.js` | Shared dashboard shell with offline trend/range/function views |
| `annotations.py`, `quality_gate.py` | Bounded Actions warnings and opt-in quality/comparison failure policy |
| `visual_report.py` | Markdown, JSON, and optional offline Plotly HTML dashboards |
| `plan_review.py` | Unified diff previews and versioned plan preflight |
| `presentation.py`, `storage.py` | Shared escaping/tables and atomic validated persistence |
| `recovery.py` | Durable per-attempt file snapshots, scoped restoration and verification |
| `runner.py` | `pytest` / `unittest` for Python projects |
| `session.py` | JSON persistence for `RefactorPlan` |
| `reporter.py` | Check, dry-run and apply reports (Markdown; apply also JSON) |
| `config.py` | Validated YAML + environment; CLI applies explicit overrides last |
| `models.py` | Pydantic models and `AppConfig` |
| `agents/*` | Planning agents: analyzer, quality checker, deduplicator (AST fingerprint), pattern, idiomatizer (model-only) |
| `llm/router.py` | Explicit text-only OpenAI/Anthropic-compatible requests |
| `progress.py` | Opt-in stderr progress and heartbeats for CLI phases |
| `utils/code_utils.py` | Naming suggestions and model-reply fence stripping |

## Request flows

### Analyze

1. `repo.walk` → `.py` files only (per `include_patterns`).
2. `analysis.analyze_files` parses AST, extracts symbols and independent function metrics.
3. All hotspots where cyclomatic **or** cognitive complexity reaches its threshold; explicit parse diagnostics.
4. `visual_report` renders one shared result as Markdown/JSON/HTML when requested.

### Compare

`cli.compare` → `compare_revisions`: resolve exact commits, list changed paths and
Git renames, read regular blobs without checkout, analyze both snapshots using
the same configuration, match qualified function names, and render deltas.
No target imports, LLM calls, tests, or working-tree edits. See [CI.md](CI.md).
`--against` resolves a merge base without fetching. Explicit `--worktree` selects
current tracked files plus nonignored untracked Python files, not the index alone.
Optional gates and bounded GitHub warnings consume the same comparison result.

### History

`cli.history` → `history_revisions`: list up to 100 first-parent commits, select
the current source root or explicit fallback aliases, read object IDs using Git
batch mode, and reuse one parsed measurement per unique blob within that run.
Remap file paths and match adjacent complete snapshots using the shared engine.
Older unavailable source becomes a chart gap; current-head/Git/report failure
blocks main-only Pages. JSON embeds measurements/configuration; Markdown and
offline Plotly/JavaScript consume that same result, without a data branch or server.

### Deduplicate / idiomatize / pattern / check

Same default Python walk scope. Idiomatize is model-only and emits **one whole-file
change per file**. Named patterns also have an optional model path; default templates
are advisory modules. Deduplicate fingerprints self-contained top-level functions and is
suggestion-only — it proposes `utils/<stem>_<symbol>_<line>_dedup_<sha12>.py` and does
not rewrite call sites.

### Apply

`apply_changes_safe` checks all original bytes and operations, snapshots affected bytes/modes/existence,
then performs per-file atomic writes, syntax/metrics validation and opt-in target
tests. Failures and exceptions trigger scoped restoration with verification.
No Git history/index mutation occurs. This is not crash-proof or multi-file atomic;
concurrent changes and restoration failures are reported with retained backups.
See [SAFETY.md](SAFETY.md).
All modifying CLI commands now print actual returned apply outcomes and exit 1 on
failure; saved-plan replay uses the same dirty-tree warning as planning commands.

CLI configuration resolves YAML → environment → explicit options. `App` copies
an explicitly supplied resolved configuration without reapplying environment.
Model tiers/preferences were removed; requests require explicit API/model configuration.
`check` defaults to report-only, with an opt-in inclusive severity gate.
Per-rule overrides and path ignores partition active/suppressed findings before
counts and gates are computed; parse/read errors cannot be suppressed.
Noninteractive application requires `--yes`. See [API setup and migration](LLM.md).

## Distribution

- PyPI: `reducio`, entrypoint `reducio.cli:app`
- **Python 3.14+**
- Extras: `reports`, `llm`, `dev`
- Supported usage: GitHub CI (primary), PyPI, and a PyApp executable in GitHub Releases.
  The distribution is `reducio`; CLI/import remain `reducio`. See [installation status](README.md#2-pypi).

## External dependencies

| Concern | Technology |
|---------|------------|
| CLI | Typer |
| Models | Pydantic v2 |
| Parse | Standard-library Python AST (metrics and refactoring symbols) |
| Dashboards | Plotly, optional `[reports]` extra |
| LLM | HTTPX, optional `[llm]` extra, lazy-loaded on request |
| VCS | `git` CLI via subprocess (read-only) |
| Dedup | Standard-library AST fingerprint |

See [SAFETY.md](SAFETY.md) for the apply/rollback safety model and [ONBOARDING.md](ONBOARDING.md) for maintainer workflows.
