# Add reducio to GitHub CI

Create `.github/workflows/reducio.yml` in your Python repository:

For now CI installs this repository directly until the first `reducio`
release is published. The package and command are both `reducio`.
After a verified release, replace the
install step with `pip install "reducio[reports]==VERSION"`, using its exact version.

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
        run: pip install "reducio[reports] @ git+https://github.com/mementomorri/reducio.git@main"
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
For reproducible runs, replace the install URL's `@main` with a reviewed reducio
commit SHA. No model, embeddings, API key, or target-project install is needed.
Use `pull_request`, not `pull_request_target`; do not add secrets to PR analysis.

## View the results

- **Actions → reducio → run → Summary:** rendered Markdown results.
- **Artifacts → reducio-reports:** download and unzip; open `.html` in your
  browser for interactive charts. JSON contains the complete measurements.
- **Job logs:** live stages and a heartbeat every five seconds during long work.
  Add `--quiet` to hide progress (results and errors still print).

PR comparison measures whole functions in changed files, not only changed lines.
Complexity increases do **not** fail CI; missing revisions, incomplete analysis,
and report errors do. Available reports are uploaded even after a failure.
If no report was produced, inspect the failed step's logs.

This example does not publish Pages. For optional main-only dashboard hosting,
see [Reports and CI](CI.md#this-repositorys-github-actions-workflow) and this
repository's [publishing workflow](../.github/workflows/analysis.yml).
