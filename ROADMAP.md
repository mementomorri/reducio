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
| `deduplicate` — AST-fingerprint clones → proposed `utils/<stem>_<symbol>_<line>_dedup_<sha12>.py` | done (suggest-only) | Exact structural clones of standalone top-level functions; does **not** rewrite call sites. |
| `pattern` — factory/strategy/observer/singleton templates | done | Advisory modules by default; opt-in model rewrite. |
| `idiomatize` — model-proposed idiomatic rewrites | done (model-only) | Requires `--llm-api`/`--model`; proposals are reviewed, never trusted. |
| Thresholds | partial | `cyclomatic_complexity` drives hotspots/checks, `lines_of_code` drives `long_function`; `cognitive_complexity` is accepted but not yet used. |
| Apply — whole-file byte checks, file snapshots, syntax/metrics checks | done (bounded) | No Git writes; opt-in tests; verified scoped recovery. Not crash-proof/multi-file atomic. |
| Session persistence / replay (`apply`, `sessions`, `report`) | done | JSON under `.reducio/sessions/` (git-ignored automatically). |
| Explicit compatible APIs | done | Optional `[llm]`; OpenAI Chat Completions or Anthropic Messages format. |
| Config: `.reducio.yaml` + `REDUCIO_*` env overrides | done | |

## Enhancement opportunities

These are **not shipped capabilities or delivery commitments**; they record the
gap between the original vision and the tool, ordered from clarity to features:

- [ ] **Enforced local-only mode:** explicit remote consent, provider visibility,
  safe prompt logging.
- [ ] **Cognitive threshold policy:** define how CC and cognitive thresholds select
  findings, then apply it consistently to analysis, checks, comparisons and charts.
- [ ] **Near-miss clones:** deduplicate finds exact structural clones only;
  near-miss detection needs a fuzzy matcher.
- [ ] **Dependency/reference mapping:** resolve imports, symbols and callers for
  impact analysis; report ambiguity instead of guessing.
- [ ] **Real deduplication and pattern integration:** rewrite imports/callers and
  remove originals only when validated; measure actual LOC/complexity changes.
- [ ] **Release parity checks:** test documented commands/extras against a
  published release in a clean environment.

## Mid-term

- **Cross-file impact analysis** — a symbol-graph layer *only when a command
  consumes it* (dead-code detection, safe-rename impact, real dedup rewrite).
- **Further reporting** — hosted PR previews and optional PR comments.

## Vision (not scheduled)

Multi-agent orchestration · persistent idiom memory · MCP server · autonomous
PR-review mode · multi-language support. See [DESIGN.md](docs/DESIGN.md).
