# reducio

**Semantic code compression for Python codebases**

Analyze Python complexity, compare revisions, and review experimental refactoring
proposals. Heuristics now skip uncertain cases; file recovery is scoped and verified,
but neither tests nor safeguards prove semantic equivalence. Model proposals still
require review. See [SAFETY.md](SAFETY.md).

reducio is a **Python 3.14+** CLI and library. It only analyzes and refactors **`.py` files** in target repositories.

## Install

### 1. GitHub CI (recommended)

Use the [GitHub CI setup guide](GITHUB_CI.md) for main-branch dashboards and PR
comparisons. Reports appear in job summaries and downloadable artifacts.

### 2. PyPI

The distribution, command, and Python import are all **`reducio`**.
The maintainer confirmed Trusted Publishing configuration and a successful package
upload on 2026-09-12:

```bash
pip install reducio
pip install "reducio[reports]"     # interactive HTML dashboards
pip install "reducio[embeddings]"  # semantic duplicate detection
pip install "reducio[llm]"         # optional compatible API proposals
reducio analyze . --report
```

Release CI verifies the exact published wheel hash and its installed CLI outside
the checkout before allowing executable publication. Maintainers must configure
PyPI Trusted Publishing for the `reducio` project before tagging a release.

The GitHub Trusted Publisher must use owner `mementomorri`, repository `reducio`,
workflow filename `publish.yml`, and no environment (the current workflow has none).
Update any pending publisher registered before the repository rename to match.

### Upgrading from the previous name

Use `reducio` instead of `reducto` in commands/imports and `REDUCIO_*` instead
of `REDUCTO_*` environment variables. Configuration is now `.reducio.yaml`, and
reports/sessions use `.reducio/`. Existing `.reducto` files are left untouched;
copy any configuration or sessions you want to retain to the new locations.
There are no legacy command/import aliases. The repository and Pages links use
`mementomorri/reducio` and `https://mementomorri.github.io/reducio/`.

### 3. GitHub Releases executable

After successful PyPI verification, tagged releases built by Publish provide a Linux x64 executable
with `reports`, `embeddings` and dormant `llm` support enabled. Download the executable and matching
`.sha256` file from [GitHub Releases](https://github.com/mementomorri/reducio/releases).
The executable and release title use the pushed tag: `v0.1.0` produces
`reducio-v0.1.0`. Replace `v0.1.0` below with your chosen release tag:

```bash
sha256sum --check reducio-v0.1.0.sha256
chmod +x reducio-v0.1.0
./reducio-v0.1.0 --help
./reducio-v0.1.0 analyze . --report --format all
```

The executable is built on Ubuntu 22.04 for Linux x64 with glibc; Alpine/musl,
macOS, Windows, and ARM are not supported by this download. Python 3.14 and
dependencies install automatically on first launch, requiring internet access
and writable user storage. Semantic embeddings download their model on first use.
This is not an offline bundle. Git operations still require Git on `PATH`, and
target-project tests require their own configured environment.

Download a newer executable to upgrade; PyApp management commands are disabled.
The `version` command continues to report the Python package version.

Maintainers: the executable embeds the exact wheel uploaded by the PyPI job and
is published only after executable, report, and real-embedding smoke checks pass.
If the executable job fails after PyPI succeeds, use **Re-run failed jobs** on
that workflow run. It reuses the saved wheel without republishing to PyPI. Release
retries upload missing assets and skip identical assets; differing existing
assets fail rather than being overwritten. Existing release notes are preserved.

### Optional extras

| Extra | Purpose |
|-------|---------|
| `embeddings` | Semantic deduplication (ChromaDB + sentence-transformers) |
| `reports` | Self-contained interactive HTML dashboards (Plotly); Markdown/JSON need no extra |
| `dev` | pytest, ruff, black, mypy (contributors) |

Only these three usage routes are maintained. Contributor environment setup is
documented separately in [ONBOARDING.md](ONBOARDING.md).

## Prerequisites

- **Python 3.14+** (provisioned automatically by the Linux executable)
- *(Optional)* **Ollama** for local LLM inference
- *(Optional)* `[llm]` extra and an API token for [explicit compatible APIs](LLM.md)

## Usage

Run commands from the root of a **Python project** (with `.py` sources):

```bash
reducio analyze .              # Complexity hotspots and symbols
reducio compare . --base HEAD~1 # Changed-file complexity vs a committed revision
reducio deduplicate .          # Similar blocks → proposed utils modules
reducio idiomatize .           # Pythonic heuristics (comprehensions, etc.)
reducio pattern factory .      # Design-pattern templates
reducio check .                # Naming, function length, cyclomatic-complexity issues
reducio apply <session-id>     # Apply a saved plan
reducio sessions list          # List saved sessions
```

Tests default to **not run**. To validate edits, add `--run-tests`; configure
`test_command` (argv), or `test_python` / target `.venv` with `test_runner`
(`pytest` or `unittest`) and `test_timeout_seconds` (default 300). Missing or failing
requested tests trigger recovery. Remove retired `commit_changes` configuration;
commit reviewed changes manually. See [runner setup and recovery](SAFETY.md).

### Plan modes

| Command | What the plan contains |
|---------|-------------------------|
| `deduplicate` | Embeddings compare self-contained top-level functions and propose source-qualified utility modules; methods, closures, decorators, and unresolved dependencies are skipped with diagnostics. Call sites are **not** rewritten. |
| `pattern` | All default patterns, including singleton, propose new advisory modules. A configured model enables optional whole-module rewrites for applicable named patterns. |
| `idiomatize` | Python heuristics by default; a configured model enables optional whole-module rewrites. Both paths require behavior review. |
| `apply` | Validated diffs, file snapshots, scoped recovery, opt-in target tests and whole-file metrics. No Git writes or semantic guarantee. See [SAFETY.md](SAFETY.md). |

### Flags

Flags are command-specific, not global:

| Commands | Supported options |
| --- | --- |
| `analyze`, `compare`, `deduplicate`, `idiomatize`, `pattern`, `check`, `apply` | `--config` / `-c`, `--quiet` / `-q` (hide progress only) |
| `analyze`, `compare`, `deduplicate`, `idiomatize`, `check` | `--verbose` / `-v`, `--no-verbose` |
| `deduplicate`, `idiomatize`, `pattern` | `--dry-run` (save unified diff, diagnostics, provenance, and session JSON) |
| `idiomatize`, `pattern` | `--allow-fallback` (explicitly permit heuristic/template fallback after model failure) |
| `deduplicate`, `idiomatize`, `pattern`, `apply` | `--yes` (bypass prompts, not dirty-tree warnings) |
| `analyze`, `compare`, `check` | `--report` / `-r` |
| `deduplicate`, `idiomatize`, `pattern`, `apply` | `--run-tests` (after edits only), `--report` (Markdown + JSON, including application failures) |
| `idiomatize`, `pattern` | `--model`, `--llm-api openai\|anthropic`, `--llm-base-url` |
| `check` | `--fail-on none\|info\|warning\|critical` (default `none`) |
| `analyze`, `compare` | `--format markdown\|json\|html\|all` |
| `analyze`, `compare`, `check`, `deduplicate`, `idiomatize`, `pattern`, `apply` | `--output-dir` |
| `compare` | Required `--base`, optional `--head` (default `HEAD`) |
| `report` | `--config` / `-c`, `--path` / `-C`, `--output-dir`; optional positional session ID |
| `sessions list`, `sessions show`, `sessions cleanup` | `--path` / `-C`; cleanup also accepts nonnegative `--days` |

Model rewriting requires an explicit API format and model. See [API setup](LLM.md).
Selected-model failures stop planning by default (exit 1). `--allow-fallback`
explicitly permits fallback, with a warning and recorded provenance. A valid
unchanged model response is not a failure and does not trigger heuristics.
Model planning sends source text to the configured endpoint, including during dry runs.
There is no model discovery or provider switching. In CI/non-TTY, nonempty application
requires explicit `--yes`; dry runs and empty plans do not require approval.

For `analyze` and `compare`, add `--report --format all` for Markdown, JSON, and an
offline HTML dashboard, or choose one format. `--output-dir` controls where those
reports go. Comparison is informational; parse/read failures exit nonzero and
produce incomplete reports. See [Reports and CI](CI.md) and [Metrics v2](METRICS.md).

Generated plans print `Session ID: …`; dry-runs print `Dry run report: …`.
Full unified diffs print before approval, including `--yes`, and in `sessions show`.
Reports default to `<target>/.reducio`; sessions remain in its `sessions/` directory.
Explicit relative `--output-dir` paths are relative to the caller's working directory
and do not move sessions. Use `reducio report -C /path/to/target` for retrieval;
specify the same `--output-dir` when overridden. Old reports are not migrated or
automatically searched. Incomplete plans remain inspectable but cannot be applied.
An empty plan skips application. Successful application and ordinary declined
approval exit 0; failed application exits 1 with a reason on stderr. Declining
the dirty-tree warning exits 1. Input/configuration errors exit 2. Quality findings
and complexity regressions alone do not fail CI.

### Configuration precedence

For model, verbosity, and local preference: **explicit CLI options → environment
→ selected YAML file → built-in defaults**. Omitted options preserve lower-level
settings; `--no-verbose` overrides enabled verbosity and `--model ""` clears a
configured model. This replaces the previous environment-over-CLI behavior.

`--config` selects exactly that file; otherwise use the first existing
`.reducio.yaml` in the current working directory, then `~/.reducio.yaml`.
Files are not merged and discovery is not relative to a separate analysis target.
An empty file is valid; a missing explicit file or malformed configuration fails.
The supported environment settings are `REDUCIO_MODEL`, `REDUCIO_VERBOSE`, and
`REDUCIO_PREFER_LOCAL`. Boolean values accept true/false, yes/no, on/off, or 1/0
(case-insensitive); empty values are ignored, other values fail.

For library callers, an explicit `AppConfig` passed to `App` is copied and used
as resolved; it is not overridden again by environment variables. Omitting it
loads file/environment settings. CLI approval still requires explicit `--yes`
to bypass prompts; other modifier configuration policies remain separate work.

## Architecture

Single Python process: Typer CLI → `App` → `Workspace` (walk `*.py`, tree-sitter, git, pytest) + agents (optional compatible APIs + optional embeddings). Plans persist under `.reducio/sessions/`.

See [ARCHITECTURE.md](ARCHITECTURE.md).

## Maintainer documentation

| Doc | Description |
|-----|-------------|
| [ONBOARDING.md](ONBOARDING.md) | Setup, layout, CI, extension points |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Modules and request flows |
| [CI.md](CI.md) | Dashboards, revision comparison, GitHub summaries and artifacts |
| [GITHUB_CI.md](GITHUB_CI.md) | Copy-paste GitHub Actions setup for your repository |
| [METRICS.md](METRICS.md) | Versioned syntax-aware metrics and interpretation |
| [SAFETY.md](SAFETY.md) | Apply/recovery safeguards, test configuration and limitations |
| [TEST_IMPLEMENTATION.md](TEST_IMPLEMENTATION.md) | pytest and CI |
| [TEST_RULES.md](TEST_RULES.md) | Acceptance criteria |
| [DESIGN.md](DESIGN.md) | Product vision (long-form) |
| [ROADMAP.md](../ROADMAP.md) | What's shipped vs planned |

## License

[MIT](../LICENSE) © 2026 Alex Karsten
