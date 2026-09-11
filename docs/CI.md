# Reports and CI

For a copy-paste workflow for another repository, start with the short
[GitHub CI setup guide](GITHUB_CI.md).

## Local usage

```bash
pip install -e ".[reports]"  # from a source checkout; adds Plotly
reducto analyze reducto/ --report --format all --output-dir ci-reports/overview
reducto compare reducto/ --base HEAD~1 --head HEAD --report --format all --output-dir ci-reports/comparison
```

In another installed target project, use `.` or its source directory in place of
`reducto/`. No LLM or embeddings are needed. `analyze` reads current files;
`compare` reads **committed Git blobs**, ignoring staged/unstaged/untracked edits.
It does not check out revisions, import target modules, or run target tests.
The optional directory target must exist in the current checkout.

`--base` is required and means that exact revision; `--head` defaults to `HEAD`.
For a branch comparison, resolve a merge base explicitly:

```bash
git fetch origin main
reducto compare . --base "$(git merge-base origin/main HEAD)" --head HEAD --report --format all
```

Include/exclude patterns and thresholds come from one current configuration on
both sides, not each revision's old config. Pass `--config path/to/config.yaml`
to make that choice explicit. See [METRICS.md](METRICS.md) for counting rules.

## Where results appear

| Output | Purpose |
| --- | --- |
| Terminal | Counts, errors, report paths; `-v` adds details |
| Markdown | Compact summary and top-20 table, readable in GitHub's job summary |
| HTML | Offline interactive dashboard: distributions, scatter, rankings, comparison charts, complete table |
| JSON | Complete versioned measurements for automation |

`--report` alone preserves the Markdown default under the caller's `.reducto/`.
`--format markdown\|html\|json\|all` selects formats **when `--report` is present**.
`--output-dir` overrides that directory for `analyze` and `compare`. Files have
timestamped names; HTML includes its own JavaScript and needs no server/CDN.
Without the `reports` extra, Markdown and JSON still work.

Long-running commands print plain-text stages to stderr immediately before work,
including preparation, exploration, analysis, and report generation. A heartbeat
every five seconds keeps slow phases visible without implying a percentage or
completion estimate. `--quiet` / `-q` hides progress, not results or errors;
stdout remains available for scripts. Library calls are silent unless progress
is explicitly enabled. Progress stops before interactive approval prompts.

## This repository's GitHub Actions workflow

[Analysis](../.github/workflows/analysis.yml) has two analysis jobs and a main-only
publishing job:

- **overview:** on `main`/`develop` pushes and manual runs. Analyzes `reducto/`,
  checks structured results for actual functions, and includes the quality report.
- **comparison:** on pull requests targeting `main`. Fetches full history and
  compares the PR merge base against the explicit PR head SHA, scoped to
  `reducto/`. It does not use GitHub's synthetic merge commit as the head.
- **publish-pages:** after a successful overview, on `main` pushes or manual runs
  explicitly selecting `main`. Reuses that run's HTML artifact, preserves the
  landing page, and publishes the dashboard at `/dashboard/`. Never runs for PRs,
  `develop`, or manual runs on other branches. Failed analysis does not replace
  the last published dashboard. Only this job receives Pages deployment permissions.

Open **Actions → Analysis → run → Summary** for the compact results. Download
`reducto-overview` or `reducto-comparison` from the run's **Artifacts** section
(also linked in the summary), unzip it, and open its `.html` file in a browser.
PR and `develop` dashboards remain download-only. The latest successful `main`
overview is also hosted on GitHub Pages; its deployment summary includes a link.
GitHub documents [Markdown job summaries](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#adding-a-job-summary)
and [workflow artifacts](https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts).

### Enable GitHub Pages once

1. In `mementomorri/reducto`, open **Settings → Pages → Build and deployment**.
2. Set **Source** to **GitHub Actions**.
3. Push the workflow to `main`, or run **Actions → Analysis → Run workflow** with
   branch **main** selected after the workflow is there.

With the default project-domain configuration, bookmark
[the dashboard](https://mementomorri.github.io/reducto/dashboard/). It becomes
available after the first successful deployment. If a custom domain is configured,
use the link in the deployment summary instead. No local server is needed.
Optionally restrict the `github-pages` environment's deployment branches to `main`
as an additional safeguard. Setup follows GitHub's
[custom Pages workflow instructions](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

The public site contains only the existing landing HTML and latest overview HTML;
JSON, quality reports, and PR comparisons remain in Actions artifacts. Pages
updates the existing site, not a historical report archive.

Reports upload with `if: always()` so available partial results survive a failed
analysis. Missing refs, unreadable/invalid source, or report errors fail the job;
complexity regressions and quality findings alone do not. Docs-only changes yield
a successful empty comparison. Branch-protection rules are not changed by this
workflow update. A failure before report generation is explained in job logs.

To reuse the workflow elsewhere, install a trusted reducto version/source checkout
and change the target to that project's source directory. The measurement engine
parses rather than executes source, but installing a package/workflow still runs
code: keep normal PR permissions and do not use privileged `pull_request_target`
to install untrusted PR code.

The fixture corpus remains covered by pytest, including its five known invalid
Python files. It is not mixed into product overview charts. CI checks that tests
leave tracked fixture files unchanged.
