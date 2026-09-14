# Maintainer onboarding

Guide for engineers maintaining **reducio** — Python analysis, revision reporting,
and experimental refactoring. Automatic modification is not production-safe.

- Vision: [DESIGN.md](DESIGN.md)
- Architecture: [ARCHITECTURE.md](ARCHITECTURE.md)
- Apply safety model: [SAFETY.md](SAFETY.md)
- User guide: [README.md](README.md)
- Testing: [TEST_IMPLEMENTATION.md](TEST_IMPLEMENTATION.md), [TEST_RULES.md](TEST_RULES.md)

## Scope

- **Tool implementation:** Python 3.14+ package under `reducio/`
- **Target code:** `.py` files only (`include_patterns` default `["*.py"]`)
- **Tests on apply:** `pytest` or `unittest` when the target repo is a Python project

Non-Python files are ignored by the walker and report `Language.UNKNOWN` if referenced directly.

## Repository layout

| Path | Purpose |
|------|---------|
| `reducio/` | Shipped package |
| `reducio/cli.py` | Typer entrypoint |
| `reducio/services.py` | `App` orchestration |
| `reducio/workspace.py` | Repo I/O, parse, apply, git, tests |
| `reducio/parse.py` | Standard-library AST symbols |
| `reducio/agents/` | Analyzer, deduplicator, idiomatizer, pattern, quality |
| `tests/` | pytest (unit, scenario, e2e) |
| `test-python-code/python/` | Fixture corpus |
| `docs/README.md` | Primary user documentation |

## Development setup

```bash
cd /path/to/reducio
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,embeddings,reports,llm]"
reducio version
pytest tests/ -v
```

Optional: `[llm]` extra and a token for [explicit compatible APIs](LLM.md).

### Configuration

Explicit CLI options override environment, then the selected YAML file, then
defaults. An explicit `--config` must exist; otherwise discovery uses the first
existing current-directory/user config, without merging. See the
[configuration contract](README.md#configuration-precedence).

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
| `idiomatize` | `idiomatize` | Python heuristics; optional configured-model rewrite |
| `pattern` | `pattern` | Advisory modules for every default pattern; optional configured-model rewrite for named patterns |
| `check` | `check` | Naming, function length, per-function cyclomatic complexity |
| `apply` | `apply_plan` | Session JSON → dirty-tree warning, approval, guarded apply with recovery limits |

Use the [per-command flag table](README.md#flags): `pattern` and `idiomatize`
accept explicit API/model flags, configuration or environment. Plans print session IDs;
dry-runs print report paths. Failed application exits 1; invalid inputs exit 2.
`--quiet` hides progress only, while `--no-verbose` disables detailed results.
Diff previews and provenance appear in terminal output, dry-run Markdown, and
`sessions show`. Selected-model failures stop by default; `--allow-fallback`
explicitly permits heuristic/template fallback. Incomplete plans cannot apply.
Reports and sessions live under `<target>/.reducio`; use `report -C TARGET` for lookup.

Distribution name: `reducio`; CLI/import: `reducio`. Editable installation
above is for contributors. Public usage routes are CI, PyPI, and Releases executables.

## Extending

1. New command: `cli.py` → `services.py` → agent or `workspace.py`
2. New Python refactor rule: `agents/idiomatizer.py` or dedicated agent
3. Tests under `tests/`; map to [TEST_RULES.md](TEST_RULES.md) when user-visible

## CI

| Workflow | Role |
|----------|------|
| `test.yml` | Shared pytest/branch-coverage, lint, build and isolated wheel smoke gate |
| `publish.yml` | Shared verification → PyPI → published-wheel check → PyApp Release |
| `analysis.yml` | Source overview; independent PR comparison with optional gates; main-only history and Pages |

See [CI.md](CI.md) for report access and [METRICS.md](METRICS.md) before changing
counting rules. Fixtures are validated by pytest, including known parse failures.

## Smoke

```bash
reducio analyze test-python-code/python -v
reducio deduplicate test-python-code/python --dry-run
```

## Debugging

| Issue | Start here |
|-------|------------|
| CLI | `reducio/cli.py` |
| Empty plan | `reducio/agents/*` |
| Parse/symbols | `reducio/parse.py`, `reducio/repo.py` |
| Apply/rollback | `reducio/workspace.py`, `recovery.py`, `runner.py` (see [SAFETY.md](SAFETY.md)) |
| LLM | `reducio/llm/router.py` |
| Sessions | `.reducio/sessions/`, `session.py` |
