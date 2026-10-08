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
        assert any(any("[reports,llm]" in part for part in command) for command in commands)
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
    assert not any("download" in command for command in commands)
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


def _fake_release(monkeypatch, installed: set[str], version="1.2.3"):
    commands = []

    def run(command, **kwargs):
        command = list(command)
        commands.append(command)
        assert "REDUCIO_API_KEY" not in kwargs["env"] and kwargs["cwd"] != Path.cwd()
        out = ""
        if "analyze" in command:
            reports = Path(command[command.index("analyze") + 1]) / ".reducio"
            reports.mkdir()
            suffixes = ("json", "md", "html") if command[-1] == "all" else ("json",)
            for suffix in suffixes:
                (reports / f"report.{suffix}").write_text("")
        if command[-1] == "version":
            out = f"reducio {version}\n"
        elif "-c" in command and "find_spec" in command[-1]:
            out = str(any(repr(m) in command[-1] for m in installed))
        return subprocess.CompletedProcess(command, 0, out, "")

    monkeypatch.setattr(smoke_pypi.subprocess, "run", run)
    checked = []
    monkeypatch.setattr(smoke_pypi, "check_cli", lambda *args: checked.append(args))
    return commands, checked


@pytest.mark.parametrize(
    "extras,installed,spec",
    [
        ("", set(), "reducio==1.2.3"),
        ("reports", {"plotly"}, "reducio[reports]==1.2.3"),
        ("llm,reports", {"plotly", "httpx"}, "reducio[llm,reports]==1.2.3"),
    ],
)
def test_published_release_parity_per_extra(tmp_path, monkeypatch, extras, installed, spec):
    release = tmp_path / "release"
    (release / "scripts").mkdir(parents=True)
    (release / "scripts/smoke_llm.py").write_text("")
    commands, checked = _fake_release(monkeypatch, installed)
    smoke_pypi.published("1.2.3", extras, release)
    install = next(c for c in commands if "install" in c)
    assert (
        install[-1] == spec
        and install[install.index("--index-url") + 1] == "https://pypi.org/simple"
    )
    docs = next(c for c in commands if any(str(part).endswith("doc_commands.py") for part in c))
    assert docs[-1] == str(release)
    assert not checked  # check_cli encodes current behavior; old releases differ
    analyze = next(c for c in commands if "analyze" in c)
    assert analyze[-1] == ("all" if "reports" in extras else "json")
    llm = [c for c in commands if any(str(part).endswith("smoke_llm.py") for part in c)]
    assert llm == (
        [[llm[0][0], "-I", str(release / "scripts/smoke_llm.py")]] if "llm" in extras else []
    )


def test_published_release_rejects_wrong_extras(tmp_path, monkeypatch):
    _fake_release(monkeypatch, {"plotly"})
    with pytest.raises(AssertionError, match="plotly"):
        smoke_pypi.published("1.2.3", "", tmp_path)
    with pytest.raises(SystemExit, match="embeddings"):
        smoke_pypi.published("1.2.3", "embeddings", tmp_path)


def test_release_parity_workflow_is_manual_read_only_and_injection_safe():
    root = Path(__file__).resolve().parents[2]
    text = (root / ".github/workflows/release-parity.yml").read_text()
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["parity"]
    assert job["strategy"]["matrix"]["extras"] == ["", "reports", "llm"]
    step = job["steps"][-1]
    # Inputs reach the shell only through env, never interpolated into the script.
    assert "${{" not in step["run"] and step["env"]["TAG"] == "${{ inputs.tag }}"
    assert "--release-dir release" in step["run"]


def test_release_notes_pin_version_and_link_tag_docs():
    from scripts.pyapp_release import release_notes

    notes = release_notes(
        {"version": "0.2.0rc1", "tag": "v0.2.0-rc1", "commit": "c" * 40, "binary_name": "b"}
    )
    assert 'pip install "reducio[reports]==0.2.0rc1"' in notes
    assert "/blob/v0.2.0-rc1/docs/README.md" in notes
