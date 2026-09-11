# reducto

**Semantic code compression for Python codebases**

Analyze Python complexity, compare revisions, and review experimental refactoring
proposals. Automatic modification is **not production-safe**: behavior-changing
rewrites and recovery defects remain. See [SAFETY.md](SAFETY.md).

reducto is a **Python 3.14+** CLI and library. It only analyzes and refactors **`.py` files** in target repositories.

## Install

### Published releases

Check the selected [release's notes](https://github.com/mementomorri/reducto/releases)
for included features; published-package parity with this checkout is not verified.

```bash
pip install reducto
# semantic deduplication (ChromaDB + embeddings):
pip install "reducto[embeddings]"
```

### From source

```bash
git clone https://github.com/mementomorri/reducto.git
cd reducto
pip install -e ".[embeddings]"
```

### Optional extras

| Extra | Purpose |
|-------|---------|
| `embeddings` | Semantic deduplication (ChromaDB + sentence-transformers) |
| `reports` | Self-contained interactive HTML dashboards (Plotly); Markdown/JSON need no extra |
| `dev` | pytest, ruff, black, mypy (contributors) |

### Checkout-based Bash installer

From the root of a source checkout, using Python 3.14+:

```bash
PYTHON_CMD=python3.14 bash install.sh
```

The [installer](https://github.com/mementomorri/reducto/blob/main/install.sh)
uses editable installation of the current directory and includes embeddings.
It is not a standalone download-and-run installer; `INSTALL_DIR` is currently
unused. Prefer the explicit pip commands above for control over environments/extras.

### Docker

```bash
docker build -t reducto .
docker run -v "$(pwd):/work" -w /work reducto analyze .
```

## Prerequisites

- **Python 3.14+**
- *(Optional)* **Ollama** for local LLM inference
- *(Optional)* API keys for cloud models via LiteLLM

## Usage

Run commands from the root of a **Python project** (with `.py` sources):

```bash
reducto analyze .              # Complexity hotspots and symbols
reducto compare . --base HEAD~1 # Changed-file complexity vs a committed revision
reducto deduplicate .          # Similar blocks → proposed utils modules
reducto idiomatize .           # Pythonic heuristics (comprehensions, etc.)
reducto pattern factory .      # Design-pattern templates
reducto check .                # Naming, function length, cyclomatic-complexity issues
reducto apply <session-id>     # Apply a saved plan
reducto sessions list          # List saved sessions
```

### Plan modes

| Command | What the plan contains |
|---------|-------------------------|
| `deduplicate` | Embeddings find similar functions/methods; proposes `utils/<symbol>_dedup.py` (suggestion only — does **not** rewrite call sites). |
| `pattern` | All default patterns, including singleton, propose new advisory modules. A configured model enables optional whole-module rewrites for applicable named patterns. |
| `idiomatize` | Python heuristics by default; a configured model enables optional whole-module rewrites. Both paths require behavior review. |
| `apply` | Context/syntax/definition-name checks and rollback attempts. Dirty-state preservation and exceptional recovery are not reliable. See [SAFETY.md](SAFETY.md). |

### Flags

Flags are command-specific, not global:

| Commands | Supported options |
| --- | --- |
| `analyze`, `compare`, `deduplicate`, `idiomatize`, `pattern`, `check`, `apply` | `--config` / `-c`, `--quiet` / `-q` (hide progress only) |
| `analyze`, `compare`, `deduplicate`, `idiomatize`, `check` | `--verbose` / `-v`, `--no-verbose` |
| `deduplicate`, `idiomatize`, `pattern` | `--dry-run` (save descriptions and session JSON; no inline code diff) |
| `deduplicate`, `idiomatize`, `pattern`, `apply` | `--yes` (bypass prompts, not dirty-tree warnings) |
| `analyze`, `compare`, `check` | `--report` / `-r` |
| `deduplicate` | `--report` (successful apply report), `--prefer-remote` |
| `analyze`, `deduplicate`, `idiomatize` | `--model` |
| `analyze` | `--prefer-local`, `--prefer-remote` (mutually exclusive) |
| `analyze`, `compare` | `--format markdown\|json\|html\|all`, `--output-dir` |
| `compare` | Required `--base`, optional `--head` (default `HEAD`) |
| `report` | `--config` / `-c`; optional positional session ID |
| `sessions list`, `sessions show`, `sessions cleanup` | `--path` / `-C`; cleanup also accepts nonnegative `--days` |

`pattern` has no `--model` flag; set `model` in configuration or `REDUCTO_MODEL`.
Model failures may fall back to heuristics/templates without explaining the path.
Preference is not an enforced local-only mode: cloud models receive source text.

For `analyze` and `compare`, add `--report --format all` for Markdown, JSON, and an
offline HTML dashboard, or choose one format. `--output-dir` controls where those
reports go. Comparison is informational; parse/read failures exit nonzero and
produce incomplete reports. See [Reports and CI](CI.md) and [Metrics v2](METRICS.md).

Generated plans print `Session ID: …`; dry-runs print `Dry run report: …`.
Inspect original/modified code in `<target>/.reducto/sessions/<id>.json` before
approval. Legacy reports still default to the caller's `.reducto/` directory.
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
`.reducto.yaml` in the current working directory, then `~/.reducto.yaml`.
Files are not merged and discovery is not relative to a separate analysis target.
An empty file is valid; a missing explicit file or malformed configuration fails.
The supported environment settings are `REDUCTO_MODEL`, `REDUCTO_VERBOSE`, and
`REDUCTO_PREFER_LOCAL`. Boolean values accept true/false, yes/no, on/off, or 1/0
(case-insensitive); empty values are ignored, other values fail.

For library callers, an explicit `AppConfig` passed to `App` is copied and used
as resolved; it is not overridden again by environment variables. Omitting it
loads file/environment settings. CLI approval still requires explicit `--yes`
to bypass prompts; other modifier configuration policies remain separate work.

## Architecture

Single Python process: Typer CLI → `App` → `Workspace` (walk `*.py`, tree-sitter, git, pytest) + agents (LiteLLM + optional embeddings). Plans persist under `.reducto/sessions/`.

See [ARCHITECTURE.md](ARCHITECTURE.md).

## Maintainer documentation

| Doc | Description |
|-----|-------------|
| [ONBOARDING.md](ONBOARDING.md) | Setup, layout, CI, extension points |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Modules and request flows |
| [CI.md](CI.md) | Dashboards, revision comparison, GitHub summaries and artifacts |
| [GITHUB_CI.md](GITHUB_CI.md) | Copy-paste GitHub Actions setup for your repository |
| [METRICS.md](METRICS.md) | Versioned syntax-aware metrics and interpretation |
| [SAFETY.md](SAFETY.md) | Apply/rollback safety model and guarantees |
| [TEST_IMPLEMENTATION.md](TEST_IMPLEMENTATION.md) | pytest and CI |
| [TEST_RULES.md](TEST_RULES.md) | Acceptance criteria |
| [DESIGN.md](DESIGN.md) | Product vision (long-form) |
| [ROADMAP.md](../ROADMAP.md) | What's shipped vs planned |

## License

[MIT](../LICENSE) © 2026 Alex Karsten
