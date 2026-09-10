# reducto Architecture

Python 3.14+ CLI for semantic compression of **Python source code**. One process: Typer CLI, in-process `Workspace`, optional embeddings.

## Overview

```
User
  → reducto.cli (Typer)
       → reducto.services.App
            → Workspace (repo walk *.py, parse, diff, git, pytest)
            → Agents (analyze, deduplicate, idiomatize, pattern, check)
            → LLMRouter (LiteLLM; Ollama local-first)
            → EmbeddingService ([embeddings] extra)
            → SessionStore (.reducto/sessions)
            → Reporter (.reducto/*.md)
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
| `git_safety.py` | Checkpoint, rollback (GitPython) |
| `runner.py` | `pytest` / `unittest` for Python projects |
| `session.py` | JSON persistence for `RefactorPlan` |
| `reporter.py` | Markdown reports |
| `config.py` | `.reducto.yaml` + env |
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

Same walk scope. Non-`.py` paths are never loaded. Idiomatize uses Python line heuristics only and
emits **one whole-file change per file** (the diff is therefore file-relative). Deduplicate is
suggestion-only — it proposes a shared `utils/<symbol>_dedup.py` module and does not rewrite call sites.

### Apply

`apply_changes_safe` is an all-or-nothing transaction: snapshot (git checkpoint, or in-memory copy on a
non-git target) → apply diffs with **context validation** → **post-apply `ast.parse`** → run pytest (if
the project looks like Python) → roll the whole batch back on *any* failure. Create diffs refuse to
overwrite an existing file. See [SAFETY.md](SAFETY.md) for the full guarantees and limits.

## Distribution

- PyPI: `reducto`, entrypoint `reducto.cli:app`
- **Python 3.14+**
- Extras: `embeddings`, `reports`, `dev`
- Docker: `.[embeddings]`, `ENTRYPOINT ["reducto"]`

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
