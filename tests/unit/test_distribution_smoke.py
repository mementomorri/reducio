"""The release gate verifies PyPI bytes before executing an installed package."""

import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import smoke_pypi


@pytest.mark.parametrize("matching", [True, False])
def test_pypi_gate_requires_exact_artifact_bytes(tmp_path, monkeypatch, matching):
    wheel = tmp_path / "reducto_code-1.0.0-py3-none-any.whl"
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
    assert "reducto-code==1.0.0" in download
    assert download[download.index("--index-url") + 1] == "https://pypi.org/simple"
