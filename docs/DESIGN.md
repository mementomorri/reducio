# reducio — product vision

This is the vision, not a runbook or a statement of shipped behavior. What exists
today is in [ROADMAP.md](../ROADMAP.md), [README.md](README.md) and
[ARCHITECTURE.md](ARCHITECTURE.md). The earlier long-form research essay
(tool survey, Tree-sitter/LSP/vector-store architecture, model tiers) was
superseded by the shipped design and removed; it remains in Git history.

## Idea: a semantic compression engine

Reduce the amount of code a person must understand to maintain a codebase:
collapse repetition, replace uncommon constructs with well-known idioms and
patterns, and show measurably where complexity grows or shrinks.

## Principles

1. **Behavior first.** No change is trusted without review; tests and recovery
   guard application, but nothing here proves semantic equivalence.
2. **Information per line.** Prefer standard-library features and familiar
   patterns over custom abstractions.
3. **Measure, don't claim.** Syntax-aware metrics and revision comparison report
   complexity changes; fewer lines alone are not an improvement verdict.
4. **Local and explicit.** Analysis is static and offline. Model use is opt-in,
   explicit about provider and model, and sends source code only when requested.

## Directions

- Cross-file symbol/reference mapping, used only by commands that need it
  (impact analysis, safe renames, real deduplication with caller rewrites).
- Near-miss clone rewriting (today they are suggestions only).
- Validated idioms with explicit preconditions and behavior tests.
- PR-review integration, persistent idiom memory, multi-language support.
