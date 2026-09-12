# reducio Architecture

Python 3.14+ CLI for semantic compression of **Python source code**. One process: Typer CLI, in-process `Workspace`, optional embeddings.

## Overview

```
User
  → reducio.cli (Typer)
       → reducio.services.App
            → Workspace (repo walk *.py, parse, diff, git, pytest)
            → Agents (analyze, deduplicate, idiomatize, pattern, check)
            → LLMRouter (LiteLLM; Ollama local-first)
            → EmbeddingService ([embeddings] extra)
            → SessionStore (.reducio/sessions)
            → Reporter (.reducio/*.md)
```

## Package map

| Module | Role |
|--------|------|
| `cli.py` | Commands, git dirty check, asyncio bridge, session subcommands |
| `services.py` | `App`: orchestrates agents, apply, embedding lazy init |
| `workspace.py` | Files, symbols, diffs, git, tests |
| `repo.py` | Walk repo; include `*.py` by default; `detect_language` → Python or unknown |
| `parse.py` | Tree-sitter symbols for refactoring; compatibility metric import |
| `metrics.py`, `analysis.py` | Shared AST metrics and complete function analysis |
| `compare.py` | Read-only Git blob snapshots, changed-file selection, function matching |
| `visual_report.py` | Markdown, JSON, and optional offline Plotly HTML dashboards |
| `diff.py` | Apply unified diffs with context validation (raises `DiffError` on mismatch) |
| `git_safety.py` | Read-only repository discovery and dirty-state warnings (GitPython) |
| `recovery.py` | Durable per-attempt file snapshots, scoped restoration and verification |
| `runner.py` | `pytest` / `unittest` for Python projects |
| `session.py` | JSON persistence for `RefactorPlan` |
| `reporter.py` | Markdown reports |
| `config.py` | Validated YAML + environment; CLI applies explicit overrides last |
| `models.py` | Pydantic models and `AppConfig` |
| `agents/*` | Planning agents (idiomatize is Python-only) |
| `llm/router.py` | LiteLLM tiers |
| `embeddings/service.py` | ChromaDB similarity for deduplication |

## Request flows

### Analyze

1. `repo.walk` → `.py` files only (per `include_patterns`).
2. `analysis.analyze_files` parses AST, extracts symbols and independent function metrics.
3. All hotspots where cyclomatic complexity ≥ threshold; explicit parse diagnostics.
4. `visual_report` renders one shared result as Markdown/JSON/HTML when requested.

### Compare

`cli.compare` → `compare_revisions`: resolve exact commits, list changed paths and
Git renames, read regular blobs without checkout, analyze both snapshots using
the same configuration, match qualified function names, and render deltas.
No target imports, LLM calls, tests, or working-tree edits. See [CI.md](CI.md).

### Deduplicate / idiomatize / pattern / check

Same default Python walk scope. Idiomatize uses Python heuristics by default, with
optional configured-model rewriting, and emits **one whole-file change per file**.
Named patterns also have an optional model path; default templates are advisory modules.
Deduplicate is
suggestion-only — it proposes a shared `utils/<symbol>_dedup.py` module and does not rewrite call sites.

### Apply

`apply_changes_safe` preflights all diffs, snapshots affected bytes/modes/existence,
then performs per-file atomic writes, syntax/metrics validation and opt-in target
tests. Failures and exceptions trigger scoped restoration with verification.
No Git history/index mutation occurs. This is not crash-proof or multi-file atomic;
concurrent changes and restoration failures are reported with retained backups.
See [SAFETY.md](SAFETY.md).
All modifying CLI commands now print actual returned apply outcomes and exit 1 on
failure; saved-plan replay uses the same dirty-tree warning as planning commands.

CLI configuration resolves YAML → environment → explicit options. `App` copies
an explicitly supplied resolved configuration without reapplying environment.
This changes precedence, not model-routing tiers or local-only enforcement.

## Distribution

- PyPI: `reducio`, entrypoint `reducio.cli:app`
- **Python 3.14+**
- Extras: `embeddings`, `reports`, `dev`
- Supported usage: GitHub CI (primary), PyPI, and a PyApp executable in GitHub Releases.
  The distribution is `reducio`; CLI/import remain `reducio`. See [installation status](README.md#2-pypi).

## External dependencies

| Concern | Technology |
|---------|------------|
| CLI | Typer |
| Models | Pydantic v2 |
| Parse | Python AST (metrics), tree-sitter-python (refactoring symbols) |
| Dashboards | Plotly, optional `[reports]` extra |
| LLM | LiteLLM |
| VCS | GitPython |
| Dedup | ChromaDB, sentence-transformers |

See [SAFETY.md](SAFETY.md) for the apply/rollback safety model and [ONBOARDING.md](ONBOARDING.md) for maintainer workflows.
