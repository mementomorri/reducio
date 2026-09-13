# Testing

Requires **Python 3.14+** (matches CI and `pyproject.toml`).

## Reliability/code-reduction review — 2026-09-13

Verified the working-tree implementation against baseline `32244f7`:

| Check | Before | After |
|---|---:|---:|
| Passing tests | 485 | 534 |
| Combined statement/branch coverage | 90.94% | 92.47% |
| Production Python physical lines (`reducio/` + `scripts/`) | 6,054 | 5,646 |
| Mandatory direct dependencies | 6 | 4 |
| Fixed-fixture scan + analysis median | 18.4 ms | 26.7 ms |

Ruff, Black, mypy, wheel/sdist build and a fresh isolated local-wheel smoke pass.
The base install has no HTTPX, NumPy, Chroma or tree-sitter; adding `[reports,llm]`
passes CLI/session and Markdown/JSON/offline-HTML overview/comparison checks plus
both mocked API contracts. Tracked fixtures are unchanged. No live API request,
model download, publication, remote CI run or full PyApp build was performed.

The 408-line reduction (6.7%) includes the new shared presentation/storage code
and release smoke additions; tests/docs are excluded. Timing uses the same 19-file,
99-function fixture corpus on Python 3.14.7, one warmup and 15 measured runs per
version. Strict decoding/path checks and compile validation add about 8 ms locally;
this is a small local benchmark, **not a speedup claim or CI performance guarantee**.

New cases in `test_review_gaps.py` cover byte-exact BOM/CRLF/encoding replay,
unreadable and nonregular sources, directory failures, incomplete plans, read-only
commands, strict configuration, AST binding/pattern checks, atomic-write failures,
safe storage, report-name collisions and legacy/v2 plan behavior. Distribution
tests assert shared verification precedes publication and no rebuild intervenes.
Embedding tests use mocked vectors, including large groups and repeated runs.
See [migration notes](MIGRATION.md) for deliberate breaking changes.

Earlier verification snapshots below remain historical.

## Section 4 verification — 2026-09-13

Verified `134ffb3` plus the test-import ordering fix: **485 passed, no expected
failures, 92.71% coverage**; CLI **92%**, API client and quality gate **100%**.
Ruff, Black, mypy, wheel/sdist build and fixture-preservation checks pass.
A fresh isolated local-wheel install passes import/version and analysis/check
Markdown reporting; the base installation contains no HTTPX. Adding `[llm]`
passes both compatible API contracts through mock transports outside the checkout.
Official OpenAI documentation informed the request schema; no live model request,
publication, remote workflow or full PyApp build was performed. Release smoke
scripts now also verify the bundled API client with fake credentials and mocks.

The tests cover inclusive severity thresholds, configuration precedence, reports
before gate failure, unattended approval, API request/response formats, sanitized
errors, deadlines, explicit fallback and saved-plan replay without an API call.
See [API setup/migration](LLM.md) and [CI policy](GITHUB_CI.md).

## Section 3 verification — 2026-09-12

Verified `fe52767` plus the fresh-local/finalizer hardening: **419 passed, no
expected failures, 92.24% coverage**; CLI **92%**. Ruff, Black, mypy and wheel/sdist
build pass. Installed-wheel CLI/Markdown/JSON/HTML smoke passes outside the checkout,
reusing existing development dependencies (not a fresh online dependency install).
Tracked fixtures are unchanged. No commit, push, new publication, remote CI run
or full PyApp build was performed by the agent.

The implementation includes conservative AST/token-aware idioms, file snapshots
without Git/index mutation, verified scoped recovery, opt-in after-only target
tests, and whole-file apply metrics. See [SAFETY.md](SAFETY.md) for limits.

Historical rename verification: the `reducio` package/CLI passed **328 tests, 5 strict expected
failures, 91.43% coverage**. Ruff, Black, mypy, wheel/sdist build, and the installed
CLI passed; the wheel contains the `reducio` namespace and entry point. No publish
or push was performed.

New contributors: start with [ONBOARDING.md](ONBOARDING.md) for environment setup, then use this file for test commands and CI mapping.

## Run tests

```bash
pip install -e ".[dev,embeddings,reports,llm]"
pytest tests/ -v
```

E2E tests run the CLI against a throwaway copy of the fixture corpus (the `sample_repo`
fixture), so they never mutate tracked files. CI re-asserts this with `git diff --exit-code
test-python-code/`.

## Layout

| Path | Scope |
|------|--------|
| `tests/unit/` | Agents, repo, AST, previews, git, workspace/recovery, persistence, API client |
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
| §3 File snapshots / recovery, no Git mutation | `tests/unit/test_git.py`, `test_workspace.py`, `test_section3_safety.py` |
| §5 Report | `test_reporter_writes_markdown` |
| §6 CLI continuity | `tests/e2e/test_cli_smoke.py` |

## Apply-safety regression tests

These exercise specific safeguards described in [SAFETY.md](SAFETY.md), not
universal behavior-preservation or recovery guarantees:

| Checked case | Test |
|-----------|------|
| Idiomatize apply lands at correct lines; docstring intact | `tests/unit/test_apply_idiomatize.py` |
| No valid `.py` becomes invalid after `idiomatize --yes` | `tests/e2e/test_cli_smoke.py::test_idiomatize_never_breaks_valid_python` |
| Exact original-byte mismatch rejects stale plans before writes | `tests/unit/test_workspace.py`, `test_review_gaps.py` |
| Invalid Python / create-over-existing / non-git failure roll back | `tests/unit/test_workspace.py` |
| Explicit compatible APIs (mocked; no live calls) | `tests/unit/test_router.py` |

## Lint

```bash
ruff check reducio/ tests/ scripts/
black --check reducio/ tests/ scripts/
mypy reducio/ --ignore-missing-imports
```

Coverage target: `reducio/` package, minimum **90% combined statement/branch coverage**
locally and in CI (`--cov-branch`; see `pyproject.toml`). Earlier percentages below
are line-only historical snapshots and are not directly comparable.
Historical section 2 run (2026-09-11, on top of `7d36387`): **328 passed, 5 strict
expected failures, 91.43% coverage**; CLI **92%**, configuration **100%**. Ruff,
Black, mypy, wheel/sdist build, and installed-wheel CLI/report smoke passed.
Tracked fixtures are unchanged. No public release, remote CI run, or full local
PyApp build was performed. Those expected failures documented then-open section 3 blockers.

Historical section 1 run: **266 tests passed / 85.15% coverage** (2026-09-11, section 1
implementation on top of `2ca053b`). CLI statement coverage is **83%**, and
configuration coverage is **100%**. Ruff, Black, mypy, and wheel/sdist build passed;
tracked fixtures are unchanged. This is local verification, not a new remote CI run.
Historical snapshots: 193 tests / 80.87% after progress reporting, 169 / 80.88%
after metrics/reporting, and 120 / 72.16% before metrics v2. See [ASSESSMENT.md](ASSESSMENT.md).

Metric contracts are in `tests/unit/test_metrics_v2.py`; isolated Git comparisons
(including dirty-tree preservation, renames, invalid revisions/source, and empty
changes) in `test_compare.py`; report agreement, escaping, optional dependencies,
and in-process CLI exit behavior in `test_visual_report.py`. CLI subprocess smoke
tests and `CliRunner` tests are included in coverage. Section 2 enables
`[tool.coverage.run] patch = ["subprocess"]`, with pytest-cov 7+ and coverage
7.10.6+, following the [subprocess coverage guidance](https://pytest-cov.readthedocs.io/en/latest/subprocess-support.html).

Section 2 regression tests live in `test_plan_contracts.py`, `test_review_contracts.py`,
and `test_distribution_smoke.py`. They cover unsafe session paths, full diff previews,
outside-target report retrieval, actual saved-plan application, selected-model failure,
explicit fallback, dependency exclusions, and release-wheel identity checks.
The five former strict expected failures (`test_known_safety_gaps.py` and
`test_git.py`) now pass as ordinary regressions. Section 3 coverage additionally
checks closed-value idiom prerequisites, fresh-local/finalizer cases, exact
bytes/modes, staged/unstaged/untracked state, unborn repositories and worktrees,
write/runner/measurement faults, concurrent edits and failed restoration.
CLI tests cover opt-in after-only execution, reports on failure, output-directory
selection, and truthful test/recovery states.

The release workflow runs shared test/lint/build verification → `pypi` → `verify-pypi`
→ `pyapp`. PyPI consumes the verified distributions; published bytes must match the
saved wheel before installation. Public-PyPI and executable checks exercise the
common CLI/report contract and real embeddings/NumPy grouping. The shared build gate
uses a fresh environment outside the checkout for base import/CLI/reports and mocked
API smoke, without downloading a model:

```bash
python -m build
python -m scripts.smoke_pypi --local --wheel-directory dist --commit "$(git rev-parse HEAD)"
```

This does not substitute for public-PyPI identity or built-executable checks in release CI.

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
