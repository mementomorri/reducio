"""Verify the released binary using only its bootstrapped Python environment."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

EMBEDDING_CHECK = """
import asyncio
import importlib.metadata
import math
import sys
from pathlib import Path

import reducio
from reducio.embeddings.service import EmbeddingService

assert sys.version_info[:2] == (3, 14), sys.version
assert importlib.metadata.version('reducio') == sys.argv[1]
assert Path(reducio.__file__).is_relative_to(Path(sys.prefix))

async def check():
    service = EmbeddingService()
    await service.initialize()
    assert service._use_real_embeddings, 'Real embeddings failed to initialize'
    assert service.model is not None
    assert service.collection is not None, 'Chroma failed to initialize'
    vector = await service.embed_text('def add(a, b): return a + b')
    assert len(vector) == 384 and all(math.isfinite(value) for value in vector)
    service.collection.add(ids=['smoke'], embeddings=[vector], documents=['add'])
    assert service.collection.count() == 1
    assert service.collection.query(query_embeddings=[vector], n_results=1)['ids'] == [['smoke']]
    await service.shutdown()

asyncio.run(check())
"""


def check_cli(run, executable: str, root: Path, version: str) -> None:
    """Same public CLI contract for the PyPI installation and PyApp binary."""
    assert run(executable, "version", capture=True).stdout.strip() == f"reducio {version}"
    target = root / "contract-target"
    target.mkdir()
    source = target / "sample.py"
    source.write_text("def value():\n    return 1\n")
    config = root / "contract.yaml"
    config.write_text("{}\n")
    run("git", "-C", str(target), "init")
    run("git", "-C", str(target), "add", "sample.py")
    run(
        "git",
        "-C",
        str(target),
        "-c",
        "user.name=Smoke",
        "-c",
        "user.email=smoke@example.invalid",
        "commit",
        "-m",
        "base",
    )
    source.write_text("def value():\n    return 2\n")
    run("git", "-C", str(target), "add", "sample.py")
    run(
        "git",
        "-C",
        str(target),
        "-c",
        "user.name=Smoke",
        "-c",
        "user.email=smoke@example.invalid",
        "commit",
        "-m",
        "head",
    )
    for command in ("analyze", "compare"):
        extra = ["--base", "HEAD~1"] if command == "compare" else []
        run(
            executable,
            command,
            str(target),
            *extra,
            "--config",
            str(config),
            "--report",
            "--format",
            "all",
        )
    run(executable, "check", str(target), "--config", str(config), "--report")
    assert run(
        executable, "report", "-C", str(target), "--config", str(config), capture=True
    ).stdout
    for suffix in ("md", "json", "html"):
        assert list((target / ".reducio").glob(f"*.{suffix}")), suffix
    run(executable, "idiomatize", str(target), "--config", str(config), "--dry-run", "--quiet")
    session = json.loads(next((target / ".reducio/sessions").glob("*.json")).read_text())["plan"]
    assert session["complete"] and session["provenance"]
    run(executable, "sessions", "show", session["session_id"], "-C", str(target))
    assert source.read_text() == "def value():\n    return 2\n"


def smoke(executable: Path, version: str) -> None:
    executable = executable.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="reducio-pyapp-smoke-") as temporary:
        root = Path(temporary)
        install = root / "installation"
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("PYTHON", "REDUCIO_", "PYAPP_", "HF_"))
            and key not in {"VIRTUAL_ENV", "CONDA_PREFIX"}
        }
        env.update(
            {
                "PYAPP_INSTALL_DIR_REDUCIO": str(install),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "XDG_DATA_HOME": str(root / "data"),
                "HF_HOME": str(root / "huggingface"),
                "TORCH_HOME": str(root / "torch"),
                "PIP_CACHE_DIR": str(root / "pip"),
            }
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

        print("Checking first launch: install Python and all requested dependencies", flush=True)
        run(str(executable), "--help")
        installed_python = install / "bin/python"
        assert installed_python.is_file(), "PyApp did not create its own Python environment"
        assert run(str(executable), "version", capture=True).stdout.strip() == f"reducio {version}"
        fixture = root / "fixture"
        fixture.mkdir()
        (fixture / "sample.py").write_text("def add(a, b):\n    return a + b\n")
        config = root / "empty.yaml"
        config.write_text("{}\n")
        reports = root / "reports"
        print("Checking analysis and Markdown/JSON/HTML reports", flush=True)
        run(
            str(executable),
            "analyze",
            str(fixture),
            "--config",
            str(config),
            "--report",
            "--format",
            "all",
            "--output-dir",
            str(reports),
        )
        for extension in ("md", "json", "html"):
            files = list(reports.glob(f"*.{extension}"))
            assert len(files) == 1 and files[0].stat().st_size > 0, extension
        result = json.loads(next(reports.glob("*.json")).read_text())
        assert result["complete"] and result["total_symbols"] >= 1, result
        check_cli(run, str(executable), root, version)
        print("Checking real embeddings and Chroma (first use downloads the model)", flush=True)
        run(str(installed_python), "-I", "-c", EMBEDDING_CHECK, version)
        run(str(installed_python), "-I", "-c", Path(__file__).with_name("smoke_llm.py").read_text())
        assert run(str(executable), "version", capture=True).stdout.strip() == f"reducio {version}"
        print("PyApp smoke checks passed", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("version")
    args = parser.parse_args()
    smoke(args.executable, args.version)
