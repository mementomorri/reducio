# reducio

Optional model proposals: [API setup and migration](docs/LLM.md).

**Semantic code compression for Python codebases.**

Install, usage, and architecture: **[docs/README.md](docs/README.md)**
What's shipped vs planned: **[ROADMAP.md](ROADMAP.md)**

Start with the [GitHub CI setup guide](docs/GITHUB_CI.md) for reports and revision
comparisons. The other supported routes are PyPI and a GitHub Releases executable;
the distribution, CLI, and Python import are all **`reducio`**.
PyPI publication is configured and the maintainer has confirmed a successful upload.
Counting rules: [Metrics v2](docs/METRICS.md).
Upgrading after the reliability cleanup: [migration notes](docs/MIGRATION.md).
Application uses file snapshots and never commits changes. Tests are opt-in with
`--run-tests`; see [safety and runner setup](docs/SAFETY.md).

Requires **Python 3.14+**. Only **`.py`** files in the target repository are analyzed.

## Everyday workflow

reducio helps reviewers see where Python changes add or reduce complexity.
Use it primarily for **read-only code review**, with optional, manually reviewed
refactoring proposals—not as proof that code is correct.

1. **While coding:** run `reducio check .` for quality findings or
   `reducio analyze .` for complexity hotspots in current files.
2. **On a PR:** compare the branch's common ancestor with `main` against the PR
   head. This covers the whole PR, not just its last commit, measuring complete
   functions in changed Python files. Review the Actions summary or HTML artifact.
3. **After merging:** rebuild history on `main` to explore size, complexity trends
   and persistent hotspots. This repo publishes history to GitHub Pages and keeps
   the latest overview alongside it. PR reports stay in Actions artifacts.

To review your committed branch locally (`reducio[reports]` adds HTML charts):

```bash
git fetch origin main
reducio compare . --against origin/main --report --format all
# Include your current edits and nonignored untracked Python files:
reducio compare . --against origin/main --worktree --report --format all
# Explore up to 100 first-parent commits, rebuilt with today's metric engine:
reducio history . --report --format all
```

Use `--base HEAD~1` instead to inspect only the last commit, or `--base HEAD
--worktree` for uncommitted work only. reducio never fetches refs automatically.
Comparison ignores uncommitted edits unless `--worktree` is explicit. Add
`--fail-on new-hotspots` or `--fail-on regressions` to enforce an optional PR gate;
otherwise complexity increases remain informational.
Reports default to `.reducio/`; open the HTML directly in a browser, without a server.

Start with the [CI setup guide](docs/GITHUB_CI.md). For optional code changes,
preview with `reducio idiomatize . --dry-run` and review before applying with
`--run-tests`. Deduplication remains suggestion-only; it does not rewrite callers.

## License

[MIT](LICENSE) © 2026 Alex Karsten
