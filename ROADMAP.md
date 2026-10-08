# reducio Roadmap

What is shipped today versus what is planned. [`docs/DESIGN.md`](docs/DESIGN.md)
holds the short product vision.

Status legend: **done** = shipped & tested · **planned** = intended next · **idea** = vision, not scheduled.

## Status: analysis/reporting shipped; modifiers remain suggestion-first

Analysis has syntax-aware metrics v2, offline HTML/JSON reports, Git revision
comparison and rebuilt history dashboards. Automatic modification is **not
production-safe**: plans are reviewable, application uses scoped, verified file
recovery, but nothing proves semantic equivalence. See [safety limits](docs/SAFETY.md).

## Current capabilities

| Capability | Status | Notes |
|------------|--------|-------|
| `analyze` — AST symbols + function-level metrics v2 | done | Static, no model; Markdown/JSON/HTML reports. |
| `compare` — revisions or explicit working tree | done | `--against` merge base, changed-file deltas, opt-in PR gates/annotations. |
| `history` — rebuilt first-parent trends | done | Configurable 100-commit default, root aliases, gaps, persistent hotspots, offline drill-down. |
| `check` — naming, function length, per-function cyclomatic complexity | done | Severity gates, per-rule overrides, per-path suppression; source errors stay fatal. |
| `deduplicate` — AST-fingerprint clones → proposed `utils/<stem>_<symbol>_<line>_dedup_<sha12>.py` | done | Suggests for structural clones; `--rewrite` turns identical same-name copies in a package into imports of one shared module (callers unchanged). |
| `pattern` — factory/strategy/observer/singleton templates | done | Advisory modules by default; opt-in model rewrite. |
| `idiomatize` — model-proposed idiomatic rewrites | done (model-only) | Requires `--llm-api`/`--model`; proposals are reviewed, never trusted. |
| Thresholds | done | Hot = CC ≥ `cyclomatic_complexity` or cognitive ≥ `cognitive_complexity`, everywhere; `lines_of_code` drives `long_function`. |
| Apply — whole-file byte checks, file snapshots, syntax/metrics checks | done (bounded) | No Git writes; opt-in tests; verified scoped recovery. Not crash-proof/multi-file atomic. |
| Session persistence / replay (`apply`, `sessions`, `report`) | done | JSON under `.reducio/sessions/` (git-ignored automatically). |
| Explicit compatible APIs | done | Optional `[llm]`; OpenAI Chat Completions or Anthropic Messages format; local-only unless `--allow-remote`. |
| Config: `.reducio.yaml` + `REDUCIO_*` env overrides | done | |

## Enhancement opportunities

These are **not shipped capabilities or delivery commitments**; they record the
gap between the original vision and the tool, ordered from clarity to features:

- [x] **Enforced local-only mode:** non-loopback API hosts need `--allow-remote`
  (or `REDUCIO_ALLOW_REMOTE`); a stderr disclosure names API, model and host; saved
  plans record host, prompt size and SHA-256 only. See [LLM.md](docs/LLM.md).
- [x] **Cognitive threshold policy:** a function is hot when CC **or** cognitive
  reaches its threshold — one predicate for analysis, checks, comparisons, gates,
  history and charts. See [METRICS.md](docs/METRICS.md).
- [x] **Near-miss clones:** leftover functions ≥90% similar (normalized AST, stdlib
  `difflib`) are suggested with their similarity; never rewritten.
- [ ] **Dependency/reference mapping:** resolve imports, symbols and callers for
  impact analysis; report ambiguity instead of guessing. Only the workspace
  name-use scan that `--rewrite` needs exists.
- [x] **Real deduplication (exact copies):** `deduplicate --rewrite` replaces identical
  same-name copies in a package with imports of one shared module, refuses
  identity-observable uses, and measures LOC/CC. Pattern integration and rewriting
  renamed clones remain open.
- [x] **Release parity checks:** the manual Release parity workflow installs a chosen
  published tag per extra in a clean venv and parses its documented commands; release
  notes pin the version. Documented commands are parsed on every commit.

## Mid-term

- **Cross-file impact analysis** — a symbol-graph layer *only when a command
  consumes it* (dead-code detection, safe-rename impact, real dedup rewrite).
- **Further reporting** — hosted PR previews (optional sticky PR comments are done:
  `REDUCIO_PR_COMMENT=true`, see [GITHUB_CI.md](docs/GITHUB_CI.md#optional-pr-comment)).

## Vision (not scheduled)

Multi-agent orchestration · persistent idiom memory · MCP server · autonomous
PR-review mode · multi-language support. See [DESIGN.md](docs/DESIGN.md).
