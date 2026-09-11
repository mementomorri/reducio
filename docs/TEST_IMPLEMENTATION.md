# Testing

Requires **Python 3.14+** (matches CI and `pyproject.toml`).

New contributors: start with [ONBOARDING.md](ONBOARDING.md) for environment setup, then use this file for test commands and CI mapping.

## Run tests

```bash
pip install -e ".[dev,embeddings,reports]"
pytest tests/ -v
```

E2E tests run the CLI against a throwaway copy of the fixture corpus (the `sample_repo`
fixture), so they never mutate tracked files. CI re-asserts this with `git diff --exit-code
test-python-code/`.

## Layout

| Path | Scope |
|------|--------|
| `tests/unit/` | Agents, repo, diff, parse, git, workspace, session, LLM router |
| `tests/scenario/` | Scenarios mapped to [TEST_RULES.md](TEST_RULES.md) |
| `tests/e2e/` | CLI smoke against `test-python-code/python` |
| `test-python-code/` | Fixture corpus (not shipped); used by unit/e2e tests |

Shared fixtures live in `tests/conftest.py` (`fixture_repo_root`, `fixture_files`, `sample_repo`, `temp_git_repo`).

## TEST_RULES mapping

| TEST_RULES | Automated test |
|------------|----------------|
| §1 Python-only recognition | `tests/scenario/test_test_rules.py::test_repo_detects_python_only` |
| §1 Project mapping | `test_analyze_returns_symbols`, `test_analyze_returns_symbols_and_hotspots` |
| §2 Cross-file dedup | `test_dedup_stub_plan_on_duplicate_pair`, `test_deduplicate_groups_extracted_validator_blocks` |
| §2 Idiomatic Python | `test_idiom_list_comp` |
| §2 Pattern injection | `test_pattern_strategy_on_complex_conditionals` |
| §3 Git checkpoint / rollback | `tests/unit/test_git.py`, `test_workspace.py` |
| §5 Report | `test_reporter_writes_markdown` |
| §6 CLI continuity | `tests/e2e/test_cli_smoke.py` |

## Apply-safety regression tests

These exercise specific safeguards described in [SAFETY.md](SAFETY.md), not
universal behavior-preservation or recovery guarantees:

| Checked case | Test |
|-----------|------|
| Idiomatize apply lands at correct lines; docstring intact | `tests/unit/test_apply_idiomatize.py` |
| No valid `.py` becomes invalid after `idiomatize --yes` | `tests/e2e/test_cli_smoke.py::test_idiomatize_never_breaks_valid_python` |
| Context mismatch / truncation drift raises `DiffError` | `tests/unit/test_diff.py` |
| Invalid Python / create-over-existing / non-git failure roll back | `tests/unit/test_workspace.py` |
| LLM tier/local/remote routing | `tests/unit/test_router.py` |

## Lint

```bash
ruff check reducto/
black --check reducto/
mypy reducto/ --ignore-missing-imports
```

Coverage target: `reducto/` package (minimum 60% in CI; see `pyproject.toml`).
Latest local run: **266 tests passed / 85.15% coverage** (2026-09-11, section 1
implementation on top of `2ca053b`). CLI statement coverage is **83%**, and
configuration coverage is **100%**. Ruff, Black, mypy, and wheel/sdist build passed;
tracked fixtures are unchanged. This is local verification, not a new remote CI run.
Historical snapshots: 193 tests / 80.87% after progress reporting, 169 / 80.88%
after metrics/reporting, and 120 / 72.16% before metrics v2. See [ASSESSMENT.md](ASSESSMENT.md).

Metric contracts are in `tests/unit/test_metrics_v2.py`; isolated Git comparisons
(including dirty-tree preservation, renames, invalid revisions/source, and empty
changes) in `test_compare.py`; report agreement, escaping, optional dependencies,
and in-process CLI exit behavior in `test_visual_report.py`. CLI subprocess smoke
tests remain; the new `CliRunner` tests are included in coverage.

`test_cli_contracts.py` covers actual returned apply outcomes, empty/declined
plans, saved-plan dirty warnings, dry-run paths/session IDs, configuration
precedence, and invalid inputs. `test_config.py` covers configuration errors and
resolved service settings. Help tests run with normal and forced-color output;
strip ANSI styling before checking option spelling, not from the actual CLI.

## CI analysis job

`.github/workflows/analysis.yml` runs a source overview on pushes/manual runs and
a separate merge-base-to-PR-head comparison on pull requests. Reports use distinct
non-hidden directories and artifacts; Markdown is included in each job summary.
The overview validates JSON counts rather than grepping terminal output.
See [CI.md](CI.md) for commands and artifact access. The five invalid fixture files
are tested as explicit unavailable measurements; they are not silently treated as
zero-complexity functions or included in product overview charts.
