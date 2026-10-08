"""Verify PyPI serves the saved release wheel, then exercise an isolated install."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.pyapp_release import digest, package_metadata
from scripts.smoke_pyapp import check_cli


def _isolated(root: Path):
    """A runner with a scrubbed environment and a fresh venv under `root`."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "PIP_", "REDUCIO_"))}
    env.update(PIP_CONFIG_FILE=os.devnull, XDG_CACHE_HOME=str(root / "cache"))

    def run(*command: str, capture: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(
            command, cwd=root, env=env, check=True, text=True, capture_output=capture, timeout=1200
        )

    run(sys.executable, "-m", "venv", str(root / "venv"))
    return run


OPTIONAL = {"reports": "plotly", "llm": "httpx"}


def published(version: str, extras: str, release: Path) -> None:
    """Parity of one already-published release: install it as documented, per extra."""
    requested = {e for e in extras.split(",") if e}
    if unknown := requested - OPTIONAL.keys():
        raise SystemExit(f"Unknown extras: {', '.join(sorted(unknown))}")
    spec = (
        f"reducio[{','.join(sorted(requested))}]=={version}" if requested else f"reducio=={version}"
    )
    with tempfile.TemporaryDirectory(prefix="reducio-parity-") as temporary:
        root = Path(temporary)
        run = _isolated(root)
        python, executable = str(root / "venv/bin/python"), str(root / "venv/bin/reducio")
        run(python, "-m", "pip", "install", "--index-url", "https://pypi.org/simple", spec)
        assert run(executable, "version", capture=True).stdout.strip() == f"reducio {version}"
        # Exactly the requested optional dependencies are present.
        for extra, module in OPTIONAL.items():
            present = (
                f"import importlib.util; print(importlib.util.find_spec({module!r}) is not None)"
            )
            found = run(python, "-I", "-c", present, capture=True).stdout.strip() == "True"
            assert found == (extra in requested), f"{module} presence does not match [{extras}]"
        # Commands documented at the release's own tag must exist in what PyPI serves.
        run(python, "-I", str(Path(__file__).with_name("doc_commands.py")), str(release))
        # Version-stable contract only: newer smoke checks (check_cli) assume current behavior.
        target = root / "target"
        target.mkdir()
        (target / "sample.py").write_text("def value():\n    return 1\n")
        formats = "all" if "reports" in requested else "json"
        run(executable, "analyze", str(target), "--report", "--format", formats)
        run(executable, "check", str(target))
        for suffix in ("json", *(("md", "html") if "reports" in requested else ())):
            assert list((target / ".reducio").glob(f"*.{suffix}")), f"no {suffix} report"
        if "llm" in requested:
            contract = release / "scripts/smoke_llm.py"  # the release's own API contract
            run(
                python,
                "-I",
                str(contract if contract.is_file() else Path(__file__).with_name("smoke_llm.py")),
            )
        print(f"Published {spec} matches its documentation", flush=True)


def smoke(wheel_directory: Path, commit: str, *, local: bool = False) -> None:
    package = package_metadata(wheel_directory, commit)
    with tempfile.TemporaryDirectory(prefix="reducio-pypi-") as temporary:
        root = Path(temporary)
        run = _isolated(root)
        python = str(root / "venv/bin/python")
        version = package["version"]
        wheels = [Path(package["wheel"])]
        if not local:
            # Fetch by exact version from public PyPI, never from the checkout/artifact.
            run(
                python,
                "-m",
                "pip",
                "download",
                "--index-url",
                "https://pypi.org/simple",
                "--no-cache-dir",
                "--no-deps",
                "--only-binary=:all:",
                "--dest",
                str(root / "download"),
                f"reducio=={version}",
            )
            wheels = list((root / "download").glob("*.whl"))
            assert len(wheels) == 1 and digest(wheels[0]) == digest(
                Path(package["wheel"])
            ), "PyPI wheel differs from the published artifact"
        if local:
            run(
                python,
                "-m",
                "pip",
                "install",
                "--index-url",
                "https://pypi.org/simple",
                str(wheels[0]),
            )
            run(
                python,
                "-I",
                "-c",
                "import reducio.cli, importlib.util; assert all(importlib.util.find_spec(name) is None for name in ('httpx', 'plotly'))",
            )
        run(
            python,
            "-m",
            "pip",
            "install",
            "--index-url",
            "https://pypi.org/simple",
            f"{wheels[0]}[reports,llm]",
        )
        check_cli(run, str(root / "venv/bin/reducio"), root, version)
        run(python, "-I", "-c", Path(__file__).with_name("smoke_llm.py").read_text())
        print(
            "Local wheel verified" if local else "Published PyPI installation verified", flush=True
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-directory", type=Path)
    parser.add_argument("--commit")
    parser.add_argument(
        "--local",
        action="store_true",
        help="Verify the built wheel without PyPI lookup or model downloads",
    )
    parser.add_argument("--published", metavar="VERSION", help="Check an existing PyPI release")
    parser.add_argument("--extras", default="", help="Comma-separated extras for --published")
    parser.add_argument(
        "--release-dir", type=Path, default=Path("."), help="Checkout of the release tag (docs)"
    )
    args = parser.parse_args()
    if args.published:
        published(args.published, args.extras, args.release_dir)
    elif args.wheel_directory and args.commit:
        smoke(args.wheel_directory, args.commit, local=args.local)
    else:
        parser.error("use --wheel-directory and --commit, or --published VERSION")
