# Reports and CI

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

## This repository's GitHub Actions workflow

[Analysis](../.github/workflows/analysis.yml) has two independent jobs:

- **overview:** on `main`/`develop` pushes and manual runs. Analyzes `reducto/`,
  checks structured results for actual functions, and includes the quality report.
- **comparison:** on pull requests targeting `main`. Fetches full history and
  compares the PR merge base against the explicit PR head SHA, scoped to
  `reducto/`. It does not use GitHub's synthetic merge commit as the head.

Open **Actions → Analysis → run → Summary** for the compact results. Download
`reducto-overview` or `reducto-comparison` from the run's **Artifacts** section
(also linked in the summary), unzip it, and open its `.html` file in a browser.
The HTML dashboard is an artifact, not a GitHub-hosted interactive page.
GitHub documents [Markdown job summaries](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#adding-a-job-summary)
and [workflow artifacts](https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts).

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
