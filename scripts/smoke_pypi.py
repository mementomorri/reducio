"""Verify PyPI serves the saved release wheel, then exercise an isolated install."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.pyapp_release import digest, package_metadata
from scripts.smoke_pyapp import EMBEDDING_CHECK, check_cli


def smoke(wheel_directory: Path, commit: str, *, local: bool = False) -> None:
    package = package_metadata(wheel_directory, commit)
    with tempfile.TemporaryDirectory(prefix="reducio-pypi-") as temporary:
        root = Path(temporary)
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("PYTHON", "PIP_", "REDUCIO_", "HF_"))
        }
        env.update(
            PIP_CONFIG_FILE=os.devnull,
            HF_HOME=str(root / "models"),
            XDG_CACHE_HOME=str(root / "cache"),
        )

        def run(*command: str, capture: bool = False) -> subprocess.CompletedProcess:
            return subprocess.run(
                command,
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=capture,
                timeout=1200,
            )

        run(sys.executable, "-m", "venv", str(root / "venv"))
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
        extras = "reports,llm" if local else "reports,embeddings,llm"
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
                "import reducio.cli, importlib.util; assert all(importlib.util.find_spec(name) is None for name in ('httpx', 'tree_sitter', 'chromadb', 'numpy'))",
            )
        run(
            python,
            "-m",
            "pip",
            "install",
            "--index-url",
            "https://pypi.org/simple",
            f"{wheels[0]}[{extras}]",
        )
        check_cli(run, str(root / "venv/bin/reducio"), root, version)
        run(python, "-I", "-c", Path(__file__).with_name("smoke_llm.py").read_text())
        if not local:
            run(python, "-I", "-c", EMBEDDING_CHECK, version)
        print(
            "Local wheel verified" if local else "Published PyPI installation verified", flush=True
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-directory", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument(
        "--local",
        action="store_true",
        help="Verify the built wheel without PyPI lookup or model downloads",
    )
    args = parser.parse_args()
    smoke(args.wheel_directory, args.commit, local=args.local)
