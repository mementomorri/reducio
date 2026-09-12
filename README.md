# reducio

**Semantic code compression for Python codebases.**

Install, usage, and architecture: **[docs/README.md](docs/README.md)**
What's shipped vs planned: **[ROADMAP.md](ROADMAP.md)**

Start with the [GitHub CI setup guide](docs/GITHUB_CI.md) for reports and revision
comparisons. The other supported routes are PyPI and a GitHub Releases executable;
the distribution, CLI, and Python import are all **`reducio`**.
PyPI publication is configured and the maintainer has confirmed a successful upload.
Counting rules: [Metrics v2](docs/METRICS.md).
Application uses file snapshots and never commits changes. Tests are opt-in with
`--run-tests`; see [safety and runner setup](docs/SAFETY.md).

Requires **Python 3.14+**. Only **`.py`** files in the target repository are analyzed.

## License

[MIT](LICENSE) © 2026 Alex Karsten
