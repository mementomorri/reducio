"""Tagged distributions must carry the tag version in metadata and the CLI."""

import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest
import yaml

from scripts.release_version import stamp_version, tag_version


@pytest.mark.parametrize(
    "tag,expected",
    [("v0.1.0", "0.1.0"), ("v0.2.0-rc.1", "0.2.0rc1"), ("v2.0.dev1", "2.0.dev1")],
)
def test_tag_version(tag, expected):
    assert tag_version(tag) == expected


@pytest.mark.parametrize("tag", ["vabcdef1", "0.1.0", "v1.0+local", "v1.0\n"])
def test_reject_invalid_pypi_tags(tag):
    with pytest.raises(ValueError):
        tag_version(tag)


def test_stamp_validates_both_files_before_writing(tmp_path):
    project = tmp_path / "pyproject.toml"
    project.write_text('[project]\nversion = "1.0.0"\n')
    (tmp_path / "reducio").mkdir()
    (tmp_path / "reducio/__init__.py").write_text("# missing version\n")
    with pytest.raises(ValueError, match="declaration"):
        stamp_version(tmp_path, "v0.1.0")
    assert '"1.0.0"' in project.read_text()


def test_tag_reaches_real_wheel_and_sdist(tmp_path):
    root = Path(__file__).resolve().parents[2]
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(root / name, tmp_path / name)
    shutil.copytree(root / "reducio", tmp_path / "reducio")
    stamp_version(tmp_path, "v0.1.0")
    # Exercise the actual Hatch backend without downloading build dependencies.
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from hatchling.build import build_sdist, build_wheel; "
            "build_sdist('dist'); build_wheel('dist')",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    with zipfile.ZipFile(tmp_path / "dist/reducio-0.1.0-py3-none-any.whl") as wheel:
        assert b"Version: 0.1.0\n" in wheel.read("reducio-0.1.0.dist-info/METADATA")
        assert b'__version__ = "0.1.0"' in wheel.read("reducio/__init__.py")
    with tarfile.open(tmp_path / "dist/reducio-0.1.0.tar.gz") as sdist:
        for name in ("pyproject.toml", "reducio/__init__.py"):
            assert b'"0.1.0"' in sdist.extractfile(f"reducio-0.1.0/{name}").read()


def test_publish_passes_tag_to_build_before_verification():
    root = Path(__file__).resolve().parents[2] / ".github/workflows"
    publish = yaml.safe_load((root / "publish.yml").read_text())
    assert publish["jobs"]["verify"]["with"]["release_tag"] == "${{ github.ref_name }}"
    ci = yaml.safe_load((root / "test.yml").read_text())
    steps = ci["jobs"]["build"]["steps"]
    stamp = next(i for i, s in enumerate(steps) if "release_version.py" in s.get("run", ""))
    build = next(i for i, s in enumerate(steps) if s.get("run") == "python -m build")
    smoke = next(i for i, s in enumerate(steps) if "scripts.smoke_pypi" in s.get("run", ""))
    assert stamp < build < smoke
    assert steps[stamp]["env"]["RELEASE_TAG"] == "${{ inputs.release_tag }}"
