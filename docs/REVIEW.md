# Code review — 2026-10-05

Review of `main` at `a66a9d1`. Goal: fewer lines, same functionality, better
readability. Everything below was checked by running the code. The follow-up that
applied it (uncommitted working tree) is summarized in **Follow-up status** at the end.

## What was run

| Check | Result |
| --- | --- |
| `pytest` with `[dev,llm,reports]` | **Collection error**: `tests/unit/test_embeddings.py` imports numpy at module level |
| `pytest` + numpy, no sentence-transformers | 603 passed, **1 failed** (`test_deduplicate_sample_repo_dry_run` needs the embeddings model); coverage 93 % |
| `ruff`, `black --check`, `mypy` (CI config) | clean |
| CLI on `test-python-code/python` copy | all commands behave as documented |
| `analyze` / `check` on CPython stdlib (2370 files) | 36 s / 49 s, no crash |
| `compare --base HEAD~5`, `history` on this repo | 2.8 s / 6.4 s; history JSON is **16.7 MB** for 67 commits |

## Bugs (each reproduced)

| # | Where | Problem | Fix |
| --- | --- | --- | --- |
| 1 | `analysis.py:135` | Repeated names (`@property` getter + setter, `@overload`) are never matched. Editing an *unrelated* function in the same file reports the unchanged complex setter as **added → new hotspot**, so `--fail-on new-hotspots` fails. Repro: class with a CC-10 setter, change `other()`, run `compare --fail-on new-hotspots` → `failed`, exit 1. | When the counts are equal, pair the definitions by source order: `if len(left) == len(right): changes.extend(comparison(l, r, threshold) for l, r in zip(left, right))`. Checked: the repro passes and `test_ambiguous_functions...` still holds (its counts differ). METRICS.md says these definitions are "not guessed", so update that sentence. |
| 2 | `agents/quality_checker.py:191` | `import os`, `import re`, `import io`, `import numpy as np` are reported as **`bad_variable_name` warnings**. Reducio's own code gets 18 of them, and they count toward `--fail-on warning`. | Remove the `ast.alias` case (−2 lines). An import's name comes from the module, not from the author. Checked: the quality, gate and scenario tests still pass with this fix applied. |
| 3 | `git_safety.py:42` + every `.reducio/` writer | The plan is saved to `.reducio/sessions/` *before* the dirty-tree check. That untracked file makes every clean repo look dirty. Result: there is always a warning, and a non-interactive run without `--yes` exits 1. Recovery backups (full copies of the source) are untracked too, so a plain `git add -A` commits them. | When `.reducio/` is created, also write `.reducio/.gitignore` containing `*` (venv does the same). About 4 lines in `storage.py`. Checked: with it, the repro repo shows clean. |
| 4 | `repo.py:110-120` | **Any** symlinked directory, even `docs -> ../shared` with no Python in it, makes `analyze` and `check` incomplete (exit 1). It is also counted in `Files:`, and `check` reports it as "some Python files could not be parsed". | Skip symlinked directories with a non-fatal note, or report them only when they could hold included files. |
| 5 | `repo.py:16` | `build/`, `dist/` and `target/` are skipped at **any depth** (for example `pkg/build/__init__.py`). This can't be overridden and isn't documented: ONBOARDING lists only `exclude_patterns`. | Move these names into the `AppConfig.exclude_patterns` default and delete the constant. |
| 6 | `agents/pattern.py:56` | After a model failure (without `--allow-fallback`), `pattern` keeps calling the model for every remaining file: 5/5 calls, against 1/5 for `idiomatize`. With a dead endpoint and the 60 s timeout, that is N minutes spent on a plan that is already rejected. | Stop the file loop, as `idiomatizer.py:64` does. |
| 7 | `agents/pattern.py:126,133,136,153` | Templates build class names with `module.title()`, which gives `Auth_ValidatorStrategy`. That breaks the tool's own PascalCase rule. | Use `to_pascal_case` (already in `utils/code_utils.py`). |
| 8 | `idioms.py:106-131, 360-381` | Code that doesn't match a rewrite shape raises `ValueError` and logs "skipped candidate". Every `for` loop not directly after `x = []` warns, and so does every `if a or b:`. On stdlib: **0 edits, 8193 warnings, 56 s**. On the fixtures: 0 edits. | `return` when the shape doesn't match. Warn only when a real candidate fails its safety check. |
| 9 | tests | The tests aren't hermetic. `PatternAgent()` with no workspace saves sessions to the current directory's `.reducio/` (7 files at the repo root per run). `tests/scenario/test_test_rules.py:64,101` save into `test-python-code/python/.reducio/`. These files are git-ignored, so the CI check `git diff --exit-code test-python-code/` can't see them. `App(str(tmp_path))` also reads the developer's `~/.reducio.yaml`. | Remove the current-directory default store at `agents/base.py:31`, and use the existing `sample_repo` fixture in the scenario tests. |
| 10 | `tests/unit/test_embeddings.py:6`, `tests/e2e/test_cli_smoke.py:133` | The suite can't run without `[embeddings]`. The `embeddings` marker in `pyproject.toml` is declared but never used, and CI downloads the model on every run. | Use `pytest.importorskip("numpy")`, and mark the e2e test with `importorskip("sentence_transformers")`. |
| 11 | `.gitignore:10` | `/reducio$` matches nothing, because git patterns have no `$` anchor. Most of the file is a Go template (`go.work`, `*.test`, `*.exe`). | `/reducio` for a root binary; delete the Go section. |

## Inconsistencies

- The gate status text is built in three places with different branch order:
  `cli.py:393`, `visual_report.py:103`, and the `check` gate line in `cli.py`.
  Make it one `gate_status` computed field.
- `evaluate_gate` runs twice per `check` (`services.py:100`, `cli.py:596`).
- There are two Git layers. GitPython is used only for `is_repo`/`is_dirty`
  (`git_safety.py`, 42 lines); everything else uses the `_git` subprocess helper.
  Removing GitPython drops a dependency, and the replacement is about 8 lines.
- There are two Git blob readers. `compare._snapshot` uses 2 subprocesses per file;
  `history._read_blobs` uses one batched `cat-file`. Reuse the history one.
- The checks for retired settings are duplicated in `config.py:45-56` and
  `models.py:304-331`. The validator is named `reject_commit_setting` but rejects
  five things.
- The version is declared twice (`pyproject.toml`, `__init__.py`), plus a 49-line
  regex stamper. Use hatch `dynamic = ["version"]` from `__init__.py` so there is
  one source.
- The CLI options don't match across commands:
  - `report` and `sessions` take `--path/-C`; every other command takes a positional PATH.
  - The `-r` short flag exists on only some `--report` options.
  - `--verbose` is missing from `pattern`, `history` and `apply`.
- `pattern` auto-detect can only be reached as `reducio pattern "" PATH`;
  `reducio pattern PATH` fails with "Unknown pattern '<path>'". Either make the
  name an option or drop auto-detect.
- Config is read from the current directory, but reports and sessions go to
  `<target>/.reducio`. This is documented, but surprising for `reducio check /other/repo`.
- `_show_plan` prints every diagnostic twice: in the stdout preview and again on stderr.
- `analysis.yml` computes the merge base by hand although the CLI has `--against`.
- `installation.yml` asserts that `tree_sitter` and `chromadb` are absent, but these
  dependencies were removed long ago.
- Compare Markdown `notes` are not escaped; history notes are (`markdown_cell`).
- Several test files are named after review rounds rather than modules:
  `test_section3_safety`, `test_review_gaps`, `test_known_safety_gaps`,
  `test_daily_workflow`, `test_new_idioms`.

## Performance (measured)

| Where | Change | Gain |
| --- | --- | --- |
| `history.py:163` | Stop copying per-snapshot `symbols` (they duplicate `functions`, and the dashboard never reads them); keep the count. | History JSON **16.7 → 10.8 MB (−35 %)**; the embedded HTML (21.7 MB) shrinks by about the same |
| `metrics.py:180` | Recurse only into `ast.stmt \| ast.excepthandler \| ast.match_case` | −30 % for `functions_from_tree` on stdlib (9.9 s → 6.9 s), identical output |
| `workspace.py:113/126` | The second `validate_after()` belongs inside `if run_tests:` | One full re-measure less per apply |
| `compare.py:82-85` | Reuse `history.tree_entries` + `_read_blobs` | 2N subprocesses → 2 |
| `history.py:172` | One `git log --first-parent --format=%H%x00%cI%x00%s` instead of `git show` per commit | −100 subprocesses at the default limit |
| `idioms.py` | 7 full AST walks per file, plus more per loop | 56 s on stdlib for zero edits (see bug 8) |
| `history_view.js:75` | `inspect()` runs a `changes.filter(...)` with `JSON.stringify` for every function row; build a `Map` once | O(functions × changes) → O(n) per commit selection |

## Dead code (no production caller; about 170 lines plus their tests)

`Workspace.read_file/get_symbols/get_complexity/run_tests/is_git_clean/_resolve_path`
+ `PathEscapeError`, `parse.get_symbols` + `ParserError` (so the `except ParserError`
in `deduplicator.py` can never trigger), `metrics.measure_functions` (only used by
`test_metrics_v2.py`; move it into the tests),
`utils.calculate_complexity`, `BaseAgent.get_plan/_generate_session_id` and the dict
branch of `_file_content_path`, `SessionStore.delete_session/get_session_info/clear_cache`,
`SessionInfo.to_dict`, `EmbeddingService.embed_text`, `Reporter.generate_baseline`,
the unreachable `Repo(...)` fallback in `GitSafety._open`, `DuplicateGroup` +
`AnalyzeResult.duplicates` (always `[]`), and `Symbol.signature/references` (never set).
The `Language` enum only wraps `path.endswith(".py")`. LLM.md promises
`clear_cache()` as a compatibility no-op, so drop that line as well if the library
API is not a promise.

## Bigger simplifications (product decisions)

1. **Drop async.** There is no `gather`, task or semaphore anywhere: 19 `async def`
   in `src/` run strictly one after another. Plain functions plus `httpx.Client`
   would remove `_run`/`asyncio.run`, `pytest-asyncio`, and 137 async markers and
   mocks in the tests.
2. **Dedup by AST fingerprint instead of sentence-transformers.** A 12-line stdlib
   prototype (normalize names and constants, drop the docstring, hash `ast.dump`)
   found every intended duplicate in `test-python-code/duplicates`. It would remove
   numpy/torch (the local venv is 5.6 GB) and the model download from CI.
3. **Heuristic idiomatizer** (`idioms.py`, 422 lines): it made zero edits on stdlib
   and on the fixtures, because it only rewrites values it can prove from literals.
   Either keep it as a narrow helper next to the LLM path, or cut it to the shapes
   that actually fire.
4. **CLI.** `--quiet`, `--config` and `--output-dir` are each repeated 8–9 times
   → `Annotated` aliases. One helper could replace the near-identical bodies of
   `deduplicate`, `idiomatize` and `pattern`. Together that is about −80 lines in
   `cli.py`.
5. **Release tooling.** About 600 lines of scripts and 470 lines of tests. Consider
   `softprops/action-gh-release` together with the single version source above.

## Estimated source lines saved (`reducio/` has 6.5k lines)

| Change | Lines |
| --- | --- |
| Dead code | ≈ −170 |
| CLI `Annotated` aliases + shared plan-command helper | ≈ −80 |
| GitPython → `_git` helper | ≈ −34, and one dependency fewer |
| Single version source, retired-settings dedupe, single gate status | ≈ −45 |
| **Safe subtotal** | **≈ −330** |
| Product options: AST dedup (≈ −90, removes numpy/torch), heuristic idioms (up to −422) | up to ≈ −500 more |

## Local workspace (untracked, not repo issues)

- `reducto/` holds only stale `__pycache__` from before the rename.
- `.reducto/` (repo root) holds reports from before the rename, and
  `test-python-code/python/.reducto/` is an empty leftover from the same time.
- `venv/` (5.6 GB) is still the old `reducto` editable install: it has no plotly
  and no `reducio` entry point. Recreate it with
  `pip install -e ".[dev,embeddings,reports,llm]"`.

## Docs audit (verified against the code)

- **Stale features**
  - Ollama listed as a prerequisite, with no Ollama path in the code.
  - The removed diff engine (`reducio/diff.py`, `_change_to_diff`, `test_diff.py`) described as current.
  - `chromadb` and Tree-sitter/LSP architecture still presented as if shipped.
- **Wrong dedup descriptions**
  - It was said to cover "methods", but only top-level functions are used.
  - The output path was given as `utils/<symbol>_dedup.py`, but the real path is
    `utils/<stem>_<symbol>_<line>_dedup_<sha12>.py`.
- **Contradictory status**
  - PyPI availability was stated four different ways.
  - The landing page claimed "known behavior-changing rewrites and recovery defects remain",
    which contradicted the ROADMAP.
  - ROADMAP had an unchecked box whose text said the work was implemented, and it planned a
    `--ci` mode that already exists.
  - Test counts were stale (112 and 594).
- **Dead links:** `../TODO.md` and "TODO section N" references.
- **Gaps**
  - The extras table was missing `llm`.
  - The `dev` row was incomplete.
  - The fourth workflow (`installation.yml`) was undocumented.
  - The ONBOARDING smoke commands exited 1 on the fixtures with intentionally invalid Python.
  - The package map was missing `idioms.py`, `progress.py` and `utils/`.
  - The `cognitive_complexity`/`lines_of_code` thresholds were undocumented; `cognitive_complexity` is read nowhere.
- **Obsolete docs:** `ASSESSMENT.md` (dead links, removed APIs) and `ADVERTISING_AUDIT.md`.
  `DESIGN.md` was mostly a superseded research essay, and `TEST_IMPLEMENTATION.md` was about 75 % dated logs.

## Follow-up status

| Item | Status |
| --- | --- |
| Bug 1 repeated-name matching | Fixed: equal counts pair in source order; regression test |
| Bug 2 import names flagged | Fixed: plain imports skipped. Explicit `as` aliases are still checked (an existing contract), so `import numpy as np` is still flagged |
| Bug 3 own files dirty the tree | Fixed: `.reducio/.gitignore` written on first use; test |
| Bug 4 symlinked dirs | Docs only, by decision (SAFETY.md, docs/README.md "Scan scope") |
| Bug 5 hidden `build`/`dist`/`target` | Fixed: now part of the visible, overridable `exclude_patterns` default (MIGRATION note) |
| Bug 6 repeated model calls in `pattern` | Fixed: the first failure stops planning; test asserts 1 call |
| Bug 7 template class names | Fixed: `to_pascal_case`; test |
| Bug 8 idiom warning noise | Gone: `idioms.py` removed, `idiomatize` is model-only |
| Bug 9 non-hermetic tests | Fixed: agents need a workspace or store; CI checks ignored leftovers too |
| Bug 10 suite needs `[embeddings]` | Gone: embeddings replaced by a stdlib AST fingerprint |
| Bug 11 `.gitignore` | Fixed: Python-only file, `/reducio` |
| Performance | All applied: history drops `symbols` copies, statement-only walk, single re-validate, batched compare blobs, one `git log`, dashboard `Map` |
| Safe simplifications | Applied: dead code, GitPython, CLI `Annotated` aliases + shared plan helper, one gate status, single version source, retired-settings dedupe, `--against` in CI, escaped notes |
| Approved product changes | Applied: async dropped, AST-fingerprint dedup, `idioms.py` deleted |
| Docs audit | Fixed: ASSESSMENT/ADVERTISING_AUDIT deleted; DESIGN, TEST_IMPLEMENTATION and ROADMAP trimmed; migration notes consolidated |
| Not done (out of scope) | `Language` enum, CLI shape (`-C`, extra `--verbose`), `pattern ""` auto-detect, CWD config discovery, test-file renames, release-tooling swap, duplicate diagnostic printing, compile-validation cost, merging ARCHITECTURE/ONBOARDING and CI/GITHUB_CI |
