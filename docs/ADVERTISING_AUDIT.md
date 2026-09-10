# Landing-page claims vs implementation

Reviewed against `85c2716` plus the dashboard style/link changes. Scope:
`docs/index.html` and the implementation, not a verification of published PyPI
packages or live provider integrations. This document retains the original audit.

**Follow-up:** the landing-page copy now describes current capabilities, labels
automatic editing experimental, discloses privacy/recovery limits, and replaces
the fictional terminal output with supported example commands. Outstanding tool
work is tracked in [Enhancement opportunities](../ROADMAP.md#enhancement-opportunities).
No refactoring behavior was changed by this copy update.

## Summary

The original page sold a behavior-preserving code compressor. Today the strongest
delivered product is a Python analyzer with revision comparisons, dashboards,
and refactoring proposals. Some transformations can be applied, but neither
semantic preservation nor reliable recovery is established for all supported cases.

An in-memory probe during this review still changed `return "x == None"` into
`return "x is None"`; no target file was modified. This directly contradicts the
original hero's functionality-preservation claim, even though the rewritten Python parses.

The dark/gold visual identity is retained. GitHub, clone, releases, issue and
license links now target `mementomorri/reducto`; the logo uses a project-relative
home link so it does not navigate out of `/reducto/` on GitHub Pages.

## Original claims and remaining tool gaps

| Page claim / section | What the tool actually does | Adjustment needed |
| --- | --- | --- |
| Hero: preserves all functionality | Syntax and definition-name guards exist, but regex idioms can change literals, state, and evaluation behavior. | Restrict transformations to supported preconditions; add behavior tests. No blanket preservation guarantee. |
| Protective Enchantments / Apply: safe code, instant restoration | Checkpoint stages existing work; rollback resets to the checkpoint's parent. Runner exceptions can bypass recovery. Tests can be reported successful without running any. | Preserve staged/unstaged/untracked state; exception-safe recovery; report actual restoration and test status. |
| Human approval for every change | Approval is per plan, can be bypassed with `--yes`; dry-run reports list descriptions but omit code diffs. | Show inspectable diffs and explicit approval scope; document the opt-out, not an unconditional guarantee. |
| Demo: `deduplicate --commit .`, duplicates removed and lines saved | No `--commit` CLI option. Deduplication proposes a copied utility module and leaves original functions/call sites intact; it may add LOC. | First fix/demo-test CLI examples. Real extraction requires dependency/import/caller rewriting and behavior tests. |
| Pattern Infusion: patterns injected into existing code | Default paths create advisory template modules, not integrated refactors. Configured-model rewrites are a separate opt-in path. | Build narrow, tested integration rules or advertise suggestions, not injection. |
| Idiomatic Transmutation: context managers and broader idioms | Deterministic rules cover comprehensions, None comparisons, truthiness, and equality chains; no context-manager rule. | Add individually validated rules after fixing current unsafe ones. LLM rewrites do not establish tested support for each advertised idiom. |
| Scan: dependency-web mapping; demo shows duplicates from `analyze` | Analysis measures Python functions and symbols; it builds no dependency graph and performs no embedding duplicate search. | Separate `analyze` and `deduplicate` in the demo. Build a cross-file reference/import graph for genuine impact analysis. |
| Complexity Scrying: cyclomatic and cognitive thresholds | Both scores are measured, but hotspot selection uses only cyclomatic. Cognitive threshold configuration does not select hotspots. | Define CC/cognitive threshold policy and apply it consistently to analysis, comparison, checks, and charts. |
| Plan: LLM-powered detailed plans | Heuristics/templates are the default. A configured model enables whole-module rewrites; failures silently fall back. | Record/display the planning path and fallback reason; present diffs and validation results, not implied LLM reasoning. |
| Local-first: secrets stay local | Cloud models receive module source in prompts; local preference is not a no-network/privacy policy. | Add an enforced local-only mode, provider disclosure, explicit remote consent, and prompt-log/redaction rules. Model/embedding downloads need separate disclosure. |
| Installation: advertised experience available from PyPI | Source implements reports/comparison, but this review has not established parity with the published package. | Test the advertised install against a pinned release; link release-specific docs and disclose optional extras. |

Evidence: [idiom rules](../reducto/agents/idiomatizer.py),
[apply/recovery](../reducto/workspace.py), [Git checkpoints](../reducto/git_safety.py),
[test runner](../reducto/runner.py), [CLI](../reducto/cli.py),
[deduplication](../reducto/agents/deduplicator.py),
[patterns](../reducto/agents/pattern.py), [analysis](../reducto/analysis.py),
[plan reporting](../reducto/reporter.py), [model opt-in/fallback](../reducto/agents/base.py),
[model routing](../reducto/llm/router.py).

## Original recommendations

The copy/demo corrections below are now complete. Remaining tool enhancements
are tracked in the roadmap rather than marked as delivered by this page update.

Recommended order: quick clarity fixes first, then release-blocking safety work,
then new capabilities. Larger work does not justify leaving unsafe claims live.

1. **Make results truthful and reviewable.** Print proposed/applied/failed accurately,
   return nonzero on failed apply, show session IDs and actual diffs, disclose
   heuristic/model/fallback paths. Replace the fabricated terminal demo with a
   test-generated example; decide whether a real CLI `--commit` is wanted.
2. **Repair recovery before promoting automatic modification.** Snapshot the actual
   pre-apply state, restore only attempted changes, handle test/validation exceptions,
   and distinguish tests passed/failed/not run and rollback succeeded/failed.
3. **Constrain and validate current idioms.** Preserve literal text, accumulators,
   aliases, short-circuit evaluation, and side effects. Skip uncertain cases.
   Validate supported transformations with before/after behavior tests.
4. **Make privacy an enforceable mode, not a routing preference.** Add local-only
   enforcement, explicit remote approval/provider visibility, and safe logging.
5. **Finish the advertised analysis contract.** Define cognitive threshold semantics
   and implement them across all metric consumers. Keep diagnostics and metric
   versioning; do not equate fewer lines with better behavior.
6. **Add supported idioms incrementally.** Start with tightly scoped context-manager
   transformations, then enumerate/f-strings/etc., each with safety preconditions.
7. **Build reference/dependency analysis where it enables real refactors.** Resolve
   imports, symbols, and callers; handle ambiguity explicitly.
8. **Implement real deduplication and pattern integration on that foundation.**
   Rewrite callers/imports, preserve signatures/dependencies, remove originals only
   when validated, and report measured changes instead of assumed savings.
9. **Verify the release experience.** Install the selected release into a clean
   environment and exercise the documented commands/extras before advertising them.

The updated page highlights the existing analyzer, changed-file comparison,
offline dashboards, and main-only Pages publishing. It states Python-only scope
and the optional `reports` / `embeddings` dependencies, and points users to source
installation for the latest features without asserting published-release parity.

Until the safety work is done, suggested positioning is: **Python complexity
analysis, change-impact reports, and reviewable refactoring proposals.**

## Verification of the original style/link change

183 tests passed (80.90% coverage); Ruff, Black, and mypy passed. Both dashboards
rendered in Chromium without page errors or external requests. Checked desktop
and 390px mobile layouts; wide charts/tables scroll within their panels. Link
tests cover canonical repository URLs, local section anchors, and Pages-relative
navigation. Published endpoint availability was not independently verified.
