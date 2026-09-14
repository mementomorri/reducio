# Reports and CI

For a copy-paste workflow for another repository, start with the short
[GitHub CI setup guide](GITHUB_CI.md).

## Local usage

```bash
pip install -e ".[reports]"  # from a source checkout; adds Plotly
reducio analyze reducio/ --report --format all --output-dir ci-reports/overview
reducio compare reducio/ --base HEAD~1 --head HEAD --report --format all --output-dir ci-reports/comparison
reducio history reducio/ --report --format all --output-dir ci-reports/history
```

In another installed target project, use `.` or its source directory in place of
`reducio/`. No LLM or embeddings are needed. `analyze` reads current files;
`compare` reads **committed Git blobs** by default, ignoring local edits.
It does not check out revisions, import target modules, or run target tests.
The optional directory target must exist in the current checkout.

Choose `--base` for an exact revision (`--head` defaults to `HEAD`), or `--against`
to resolve the merge base with `HEAD`. Fetch your remote refs yourself when needed:

```bash
git fetch origin main
reducio compare . --against origin/main --report --format all
reducio compare . --against origin/main --worktree --report --format all
reducio compare . --base HEAD --worktree  # only current uncommitted work
```

Include/exclude patterns and thresholds come from one current configuration on
both sides, not each revision's old config. Pass `--config path/to/config.yaml`
to make that choice explicit. See [METRICS.md](METRICS.md) for counting rules.

`--worktree` reads actual tracked working files plus nonignored untracked Python
files, including deletions. It does not measure a staged-only snapshot or change
the index. Its report labels `head_revision` as a HEAD anchor, not the measured
contents. `--base` and `--against` are mutually exclusive; explicit `--head` cannot
accompany `--against` or `--worktree`. Missing refs fail without automatic fetching.

## History dashboard

`history` rebuilds up to **100 first-parent commits** ending at `--ref HEAD`, oldest
first. There is no data branch, database or persistent cache. Git blobs are read
in batches; identical contents are parsed once per run. Historical code is never
checked out, imported or executed. Use full Git history (`fetch-depth: 0` in CI).

Configure the limit with `--limit`, `REDUCIO_HISTORY_LIMIT`, or YAML `history_limit`
(in that precedence order). Explicit former source roots preserve continuity:

```bash
reducio history reducio/ --limit 100 --path-alias reducto/ \
  --path-alias python/ai_sidecar/ --report --format all
```

Aliases are optional, repository-relative roots, tried in order only if the
current root is absent. YAML uses `history_path_aliases: [old_source]`. Include/
exclude patterns are relative to whichever source root is selected. Root changes
are labeled; other file/function renames are not inferred by history.

Open the HTML to select a commit range, inspect any commit's functions and deltas,
or click a persistent hotspot to see its function history. Charts show physical
LOC/function count, median/p95 CC and cognitive complexity, hotspot count/share,
and new/resolved hotspots. All snapshots use the current engine/configuration;
these are remeasurements, not an archive of old tool outputs.

Older invalid/absent source appears as a **gap**, not a zero or an improvement.
Adjacent deltas across gaps are unavailable. Historical gaps alone exit 0;
incomplete latest source, Git failures or report errors exit 1 and block Pages.
Invalid input/configuration exits 2. Runtime and report size grow with the selected
history; reduce the limit or source scope for large repositories.

## Where results appear

| Output | Purpose |
| --- | --- |
| Terminal | Counts, errors, report paths; `-v` adds details |
| Markdown | Compact summary and top-20 table, readable in GitHub's job summary |
| HTML | Offline interactive dashboard: distributions, scatter, rankings, comparison charts, complete table |
| JSON | Complete versioned measurements for automation |

`--report` alone writes Markdown under `<target>/.reducio/`.
`--format markdown\|html\|json\|all` selects formats **when `--report` is present**.
`--output-dir` overrides report locations; an explicit relative path is caller-relative.
Use `reducio report -C /path/to/target` to read the latest Markdown report, adding
the same `--output-dir` when overridden. Sessions stay under the target's `.reducio/sessions/`.
Old reports are not migrated or searched in other directories. Analysis/comparison files have
timestamped names; HTML includes its own JavaScript and needs no server/CDN.
Without the `reports` extra, Markdown and JSON still work.

Long-running commands print plain-text stages to stderr immediately before work,
including preparation, exploration, analysis, and report generation. A heartbeat
every five seconds keeps slow phases visible without implying a percentage or
completion estimate. `--quiet` / `-q` hides progress, not results or errors;
stdout remains available for scripts. Library calls are silent unless progress
is explicitly enabled. Progress stops before interactive approval prompts.

## This repository's GitHub Actions workflow

[Analysis](../.github/workflows/analysis.yml) has three analysis jobs and a main-only
publishing job:

- **overview:** on `main`/`develop` pushes and manual runs. Analyzes `reducio/`,
  checks structured results for actual functions, and includes the quality report.
- **comparison:** on pull requests targeting `main`. Fetches full history and
  compares the PR merge base against the explicit PR head SHA, scoped to
  `reducio/`. It does not use GitHub's synthetic merge commit as the head.
- **history:** on `main` pushes/manual runs only. Rebuilds Git history with both
  former source-root aliases. Limit: manual `history_limit` input → repository
  Actions variable `REDUCIO_HISTORY_LIMIT` → 100.
- **publish-pages:** after successful overview **and history**, on `main` pushes or
  manual runs explicitly selecting `main`. Reuses both HTML artifacts, preserves
  the landing page, and publishes history at `/dashboard/`, with the standalone
  latest overview at `/dashboard/overview.html`. Never runs for PRs,
  `develop`, or manual runs on other branches. Failed analysis does not replace
  the last published dashboard. Only this job receives Pages deployment permissions.

Open **Actions → Analysis → run → Summary** for the compact results. Download
`reducio-overview`, `reducio-history` or `reducio-comparison` from the run's **Artifacts** section
(also linked in the summary), unzip it, and open its `.html` file in a browser.
PR and `develop` dashboards remain download-only. The latest successful `main`
history and overview are hosted on GitHub Pages; the deployment summary links there.
GitHub documents [Markdown job summaries](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#adding-a-job-summary)
and [workflow artifacts](https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts).

### Enable GitHub Pages once

1. In `mementomorri/reducio`, open **Settings → Pages → Build and deployment**.
2. Set **Source** to **GitHub Actions**.
3. Push the workflow to `main`, or run **Actions → Analysis → Run workflow** with
   branch **main** selected after the workflow is there.

With the default project-domain configuration, bookmark
[the dashboard](https://mementomorri.github.io/reducio/dashboard/). It becomes
available after the first successful deployment. If a custom domain is configured,
use the link in the deployment summary instead. No local server is needed.
Optionally restrict the `github-pages` environment's deployment branches to `main`
as an additional safeguard. Setup follows GitHub's
[custom Pages workflow instructions](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

The public site contains only landing, history and latest-overview HTML. These
include embedded metrics, paths and commit metadata, but not source code. JSON
files, quality reports and PR comparisons remain in Actions artifacts. Each run
replaces the dashboard rather than storing separate pages per past run.

Reports upload with `if: always()` so available partial results survive a failed
analysis. Missing refs, incomplete current analysis or report errors fail the job.
Comparison emits up to ten GitHub warning annotations; full reports are not capped.
Set repository variable `REDUCIO_COMPARE_FAIL_ON` to `new-hotspots` or `regressions`
for an enforced comparison gate (default `none`). Existing unchanged hotspots do
not fail it. Quality findings require their own opt-in `check` gate. Docs-only changes yield
a successful empty comparison. Branch-protection rules are not changed by this
workflow update. A failure before report generation is explained in job logs.

To reuse the workflow elsewhere, install a trusted reducio version/source checkout
and change the target to that project's source directory. The measurement engine
parses rather than executes source, but installing a package/workflow still runs
code: keep normal PR permissions and do not use privileged `pull_request_target`
to install untrusted PR code.

The fixture corpus remains covered by pytest, including its five known invalid
Python files. It is not mixed into product overview charts. CI checks that tests
leave tracked fixture files unchanged.
