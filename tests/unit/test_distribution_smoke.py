"""The release gate verifies PyPI bytes before executing an installed package."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import smoke_pypi


@pytest.mark.parametrize("matching", [True, False])
def test_pypi_gate_requires_exact_artifact_bytes(tmp_path, monkeypatch, matching):
    wheel = tmp_path / "reducio-1.0.0-py3-none-any.whl"
    wheel.write_bytes(b"expected artifact")
    monkeypatch.setattr(
        smoke_pypi, "package_metadata", lambda *args: {"version": "1.0.0", "wheel": str(wheel)}
    )
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert kwargs["cwd"] != Path.cwd()
        assert "PYTHONPATH" not in kwargs["env"]
        if "download" in command:
            destination = Path(command[command.index("--dest") + 1])
            destination.mkdir()
            shutil.copyfile(wheel, destination / wheel.name)
            if not matching:
                (destination / wheel.name).write_bytes(b"unrelated package")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(smoke_pypi.subprocess, "run", run)
    checked = []
    monkeypatch.setattr(smoke_pypi, "check_cli", lambda *args: checked.append(args))
    if matching:
        smoke_pypi.smoke(tmp_path, "a" * 40)
        assert checked
        assert any(smoke_pypi.EMBEDDING_CHECK in command for command in commands)
    else:
        with pytest.raises(AssertionError, match="differs"):
            smoke_pypi.smoke(tmp_path, "a" * 40)
        assert not checked
        assert not any("install" in command for command in commands)
    download = next(command for command in commands if "download" in command)
    assert "reducio==1.0.0" in download
    assert download[download.index("--index-url") + 1] == "https://pypi.org/simple"


def test_local_wheel_gate_avoids_model_download_and_pypi_lookup(tmp_path, monkeypatch):
    wheel = tmp_path / "reducio-1.0.0-py3-none-any.whl"
    wheel.write_bytes(b"artifact")
    monkeypatch.setattr(
        smoke_pypi, "package_metadata", lambda *args: {"version": "1.0.0", "wheel": str(wheel)}
    )
    commands = []
    monkeypatch.setattr(
        smoke_pypi.subprocess, "run", lambda command, **kw: commands.append(command)
    )
    checked = []
    monkeypatch.setattr(smoke_pypi, "check_cli", lambda *args: checked.append(args))
    smoke_pypi.smoke(tmp_path, "a" * 40, local=True)
    assert checked
    assert not any(
        "download" in command or smoke_pypi.EMBEDDING_CHECK in command for command in commands
    )
    assert any(f"{wheel}[reports,llm]" in command for command in commands)
    assert any("-I" in command for command in commands)


def test_publication_consumes_shared_verified_build():
    root = Path(__file__).resolve().parents[2]
    workflows = root / ".github/workflows"
    publish = yaml.load((workflows / "publish.yml").read_text(), Loader=yaml.BaseLoader)["jobs"]
    ci = yaml.load((workflows / "test.yml").read_text(), Loader=yaml.BaseLoader)
    assert publish["verify"]["uses"] == "./.github/workflows/test.yml"
    assert publish["pypi"]["needs"] == "verify"
    assert "workflow_call" in ci["on"]
    assert ci["jobs"]["build"]["needs"] == ["test", "lint"]
    pypi_steps = publish["pypi"]["steps"]
    assert any(
        s.get("with", {}).get("name") == "dist" and "download-artifact" in s.get("uses", "")
        for s in pypi_steps
    )
    assert not any("python -m build" in s.get("run", "") for s in pypi_steps)
    assert any("--local" in s.get("run", "") for s in ci["jobs"]["build"]["steps"])
    import tomllib

    pytest_options = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["pytest"][
        "ini_options"
    ]["addopts"]
    assert "--cov-branch" in pytest_options and "--cov-fail-under=90" in pytest_options
