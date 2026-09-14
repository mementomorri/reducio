# Add reducio to GitHub CI

Create `.github/workflows/reducio.yml` in your Python repository:

PyPI publication is configured. Replace `VERSION` below with the exact published
version you have reviewed. The package and command are both `reducio`. The new
history/worktree/rule options below require a release containing these changes;
this source update does not publish a release.

```yaml
name: reducio
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha || github.sha }}
          fetch-depth: 0
          persist-credentials: false
      - uses: actions/setup-python@v5
        with:
          python-version: '3.14'
      - name: Install reducio
        run: pip install "reducio[reports]==VERSION"
      - name: Analyze main or compare a pull request
        env:
          EVENT_NAME: ${{ github.event_name }}
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
        run: |
          if [ "$EVENT_NAME" = "pull_request" ]; then
            MERGE_BASE=$(git merge-base "$BASE_SHA" "$HEAD_SHA")
            reducio compare . --base "$MERGE_BASE" --head "$HEAD_SHA" --report --format all --output-dir ci-reports
          else
            reducio analyze . --report --format all --output-dir ci-reports
          fi
      - name: Main history
        if: github.ref == 'refs/heads/main' && github.event_name != 'pull_request'
        env:
          REDUCIO_HISTORY_LIMIT: ${{ vars.REDUCIO_HISTORY_LIMIT || '100' }}
        run: reducio history . --report --format all --output-dir ci-reports
      - name: Job summary
        if: always()
        run: |
          for report in ci-reports/*.md; do
            [ -f "$report" ] || continue
            cat "$report" >> "$GITHUB_STEP_SUMMARY"
          done
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: reducio-reports
          path: ci-reports/
          if-no-files-found: warn
```

Commit and push to `main`, open a PR targeting `main`, or select **Actions →
reducio → Run workflow** once the workflow is on your default branch. Change
`main` and the `.` analysis target if your branch/source directory differs.
Pin the published version for reproducible runs. No model, embeddings, API key, or target-project install is needed.
Use `pull_request`, not `pull_request_target`; do not add secrets to PR analysis.

## Optional PR gate and annotations

Add `--annotations github` to the comparison command for up to ten file/line
warnings, plus `--fail-on new-hotspots` to fail only when a hotspot appears or
crosses the configured CC threshold. `--fail-on regressions` also fails when a
matched function's CC or cognitive score increases (including mixed changes).
Unchanged existing hotspots do not fail. Default `none` is report-only.

Configure the default with YAML `compare_fail_on` or environment variable
`REDUCIO_COMPARE_FAIL_ON`; explicit CLI wins. No PR comments, secrets or write
permissions are required. Reports are written before a gate failure; retain
the `if: always()` summary/upload steps.

## Optional quality gate

With a release containing the section 4 changes, add this step before the summary:

```yaml
      - name: Quality gate
        run: reducio check . --fail-on warning --report --output-dir ci-reports
```

`none` (default) is report-only. `info`, `warning`, and `critical` fail on findings
at that severity or higher. Configure `check_fail_on` in YAML or
`REDUCIO_CHECK_FAIL_ON`; explicit `--fail-on` wins. Reports are written before a
gate failure (exit 1); retain the `if: always()` upload/summary steps above.
Parse failures still fail even with `none`. Invalid configuration exits 2.
This is a quality-finding gate, not a comparison/complexity-delta gate.
Nonempty application in CI/non-TTY requires explicit `--yes`; dry runs and empty
plans do not. Prefer read-only reporting in CI.

Tune individual quality rules in `.reducio.yaml`:

```yaml
quality_rules:
  naming_convention: info
  high_complexity_function: critical
  bad_variable_name: "off"  # quote off: YAML otherwise reads it as false
quality_ignores:
  "tests/**": [naming_convention, bad_parameter_name]
  "generated/**": [long_function]
```

Rule values are `info`, `warning`, `critical` or `"off"`. Other rule IDs are
`high_complexity_line` and `long_function`. Paths are relative to the analysis
target; use its usual include/exclude glob rules. Suppressed findings remain in a
separate report list and never count toward gates. Parse/read errors cannot be
disabled or downgraded by these settings. This affects `check`, not hotspot metrics.

## View the results

- **Actions → reducio → run → Summary:** rendered Markdown results.
- **Artifacts → reducio-reports:** download and unzip; open `.html` in your
  browser for interactive charts. JSON contains the complete measurements.
- **Job logs:** live stages and a heartbeat every five seconds during long work.
  Add `--quiet` to hide progress (results and errors still print).

PR comparison measures whole functions in changed files, not only changed lines.
Complexity increases fail CI **only with an enabled comparison gate**; missing
revisions, incomplete analysis and report errors always do. Available reports are
uploaded even after a failure. History displays older invalid/missing source as
gaps, but requires a complete latest snapshot. It rebuilds up to 100 first-parent
commits with today's metrics; set Actions variable `REDUCIO_HISTORY_LIMIT` to tune
the count. No data branch or model is needed.
If no report was produced, inspect the failed step's logs.

This example does not publish Pages. For optional main-only dashboard hosting,
see [Reports and CI](CI.md#this-repositorys-github-actions-workflow) and this
repository's [publishing workflow](../.github/workflows/analysis.yml).
