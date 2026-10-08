# Testing

Requires **Python 3.14+** (matches CI and `pyproject.toml`). New contributors:
start with [ONBOARDING.md](ONBOARDING.md), then use this file for commands and CI mapping.

## Run tests

```bash
pip install -e ".[dev,reports,llm]"
pytest tests/ -v
```

No model download or live API call is needed: model clients use mock transports,
and deduplication is a stdlib AST fingerprint. E2E tests run the CLI against a
throwaway copy of the fixture corpus (`sample_repo`). CI asserts that tests leave
nothing behind: `git status --porcelain --ignored test-python-code/ .reducio` must
be empty.

## Layout

| Path | Scope |
|------|--------|
| `tests/unit/` | Agents, repo, AST, previews, git, workspace/recovery, persistence, API client |
| `tests/scenario/` | Scenarios mapped to [TEST_RULES.md](TEST_RULES.md) |
| `tests/e2e/` | CLI smoke against `test-python-code/python` |
| `test-python-code/` | Fixture corpus (not shipped); used by unit/e2e tests |

Shared fixtures live in `tests/conftest.py` (`fixture_repo_root`, `fixture_files`,
`sample_repo`, `temp_git_repo`). Agents always get a temporary workspace or session
store; nothing writes into the checkout.

## TEST_RULES mapping

| TEST_RULES | Automated test |
|------------|----------------|
| §1 Python-only recognition | `tests/scenario/test_test_rules.py::test_repo_detects_python_only` |
| §1 Project mapping | `test_analyze_returns_symbols`, `test_analyze_returns_symbols_and_hotspots` |
| §2 Cross-file dedup | `test_deduplicate_groups_validator_clones`, `tests/unit/test_deduplicator.py` |
| §2 Idiomatic Python (model-only) | `tests/unit/test_idiomatizer.py`, `tests/unit/test_router.py` |
| §2 Pattern injection | `test_pattern_strategy_on_complex_conditionals` |
| §3 File snapshots / recovery, no Git mutation | `tests/unit/test_git.py`, `test_workspace.py`, `test_section3_safety.py` |
| §5 Report | `test_reporter_writes_markdown` |
| §6 CLI continuity | `tests/e2e/test_cli_smoke.py` |

Metric contracts live in `test_metrics_v2.py`; Git comparisons in `test_compare.py`;
reports and escaping in `test_visual_report.py`; the dashboard controller runs under
Node stubs in `test_history.py` (skipped only if Node is absent). Subprocess CLI tests
count toward coverage (`[tool.coverage.run] patch = ["subprocess"]`).

## Lint

```bash
ruff check reducio/ tests/ scripts/
black --check reducio/ tests/ scripts/
mypy reducio/ --ignore-missing-imports
```

Coverage gate: `reducio/` package, minimum **90% combined statement/branch coverage**
(`--cov-branch`; see `pyproject.toml`).

## Release verification

The release workflow runs shared test/lint/build verification → `pypi` →
`verify-pypi` → `pyapp`. PyPI consumes the verified distributions; published bytes
must match the saved wheel. The shared build gate checks a fresh environment
outside the checkout:

```bash
python -m build
python -m scripts.smoke_pypi --local --wheel-directory dist --commit "$(git rev-parse HEAD)"
```

**Release parity** re-tests an already-published release. Run **Actions → Release
parity** with a tag, or locally against a checkout/archive of that tag:

```bash
git archive v0.1.1 --prefix=release/ | tar -x
python -m scripts.smoke_pypi --published 0.1.1 --extras reports --release-dir release
```

Each extra (`""`, `reports`, `llm`) gets a fresh venv with `reducio[extra]==VERSION`
from public PyPI. The check asserts the reported version, that exactly the requested
optional dependencies are installed, that every `reducio …` command documented at the
tag (README, `docs/*.md`, workflows) parses against the installed CLI, that reports in
the extra's formats are written, and — for `llm` — the tag's own mocked API contract.
`tests/unit/test_docs_commands.py` runs the same documented-command parser on every
commit, so docs and flags cannot drift.

## CI analysis job

`.github/workflows/analysis.yml` runs a source overview on pushes/manual runs and a
merge-base-to-PR-head comparison (`compare --against`) on pull requests, with
optional annotations/gates. Main-only history is rebuilt in another job; Pages
requires both overview and history to succeed. See [CI.md](CI.md). The five invalid
fixture files are tested as explicit unavailable measurements.
