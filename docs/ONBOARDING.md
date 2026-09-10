# Maintainer onboarding

Guide for engineers maintaining **reducto** — a Python CLI that refactors **Python codebases** only.

- Vision: [DESIGN.md](DESIGN.md)
- Architecture: [ARCHITECTURE.md](ARCHITECTURE.md)
- Apply safety model: [SAFETY.md](SAFETY.md)
- User guide: [README.md](README.md)
- Testing: [TEST_IMPLEMENTATION.md](TEST_IMPLEMENTATION.md), [TEST_RULES.md](TEST_RULES.md)

## Scope

- **Tool implementation:** Python 3.14+ package under `reducto/`
- **Target code:** `.py` files only (`include_patterns` default `["*.py"]`)
- **Tests on apply:** `pytest` or `unittest` when the target repo is a Python project

Non-Python files are ignored by the walker and report `Language.UNKNOWN` if referenced directly.

## Repository layout

| Path | Purpose |
|------|---------|
| `reducto/` | Shipped package |
| `reducto/cli.py` | Typer entrypoint |
| `reducto/services.py` | `App` orchestration |
| `reducto/workspace.py` | Repo I/O, parse, apply, git, tests |
| `reducto/parse.py` | tree-sitter-python |
| `reducto/agents/` | Analyzer, deduplicator, idiomatizer, pattern, quality |
| `tests/` | pytest (unit, scenario, e2e) |
| `test-python-code/python/` | Fixture corpus |
| `docs/README.md` | Primary user documentation |

## Development setup

```bash
cd /path/to/reducto
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,embeddings,reports]"
reducto version
pytest tests/ -v
```

Optional: Ollama or cloud API keys for LLM-backed routing.

### Configuration

`.reducto.yaml` / `~/.reducto.yaml` / `REDUCTO_*` env vars.

```yaml
complexity_thresholds:
  cyclomatic_complexity: 8
include_patterns: ["*.py"]
exclude_patterns: [".git", "node_modules", "venv", "__pycache__"]
```

## Command map

| CLI | `App` method | Notes |
|-----|--------------|-------|
| `analyze` | `analyze` | Static; AST symbols and shared metrics v2 |
| `compare` | Direct `compare_revisions` | Read-only Git snapshots; changed-file function deltas |
| `deduplicate` | `deduplicate` | Embeddings on Python functions/methods |
| `idiomatize` | `idiomatize` | Python heuristics only |
| `pattern` | `pattern` | Template `.py` modules |
| `check` | `check` | Naming, function length, per-function cyclomatic complexity |
| `apply` | `apply_plan` | Session JSON → safe apply |

## Extending

1. New command: `cli.py` → `services.py` → agent or `workspace.py`
2. New Python refactor rule: `agents/idiomatizer.py` or dedicated agent
3. Tests under `tests/`; map to [TEST_RULES.md](TEST_RULES.md) when user-visible

## CI

| Workflow | Role |
|----------|------|
| `test.yml` | pytest, lint, wheel |
| `analysis.yml` | Source overview on pushes/manual runs; independent PR comparison job |

See [CI.md](CI.md) for report access and [METRICS.md](METRICS.md) before changing
counting rules. Fixtures are validated by pytest, including known parse failures.

## Smoke

```bash
reducto analyze test-python-code/python -v
reducto deduplicate test-python-code/python --dry-run
```

## Debugging

| Issue | Start here |
|-------|------------|
| CLI | `reducto/cli.py` |
| Empty plan | `reducto/agents/*` |
| Parse/symbols | `reducto/parse.py`, `reducto/repo.py` |
| Apply/rollback | `reducto/workspace.py`, `diff.py`, `runner.py` (see [SAFETY.md](SAFETY.md)) |
| LLM | `reducto/llm/router.py` |
| Sessions | `.reducto/sessions/`, `session.py` |
