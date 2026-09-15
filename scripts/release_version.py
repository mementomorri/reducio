"""Stamp the CI checkout with the PyPI version requested by a release tag."""

import argparse
import re
import tomllib
from pathlib import Path

from packaging.version import Version


def tag_version(tag: str) -> str:
    if not re.fullmatch(r"v[0-9][A-Za-z0-9._-]*", tag):
        raise ValueError("Use a version tag such as v0.1.0 or v0.2.0rc1")
    version = Version(tag[1:])
    if version.local is not None:
        raise ValueError("PyPI does not accept local versions")
    return str(version)


def stamp_version(root: Path, tag: str) -> str:
    version = tag_version(tag)
    project = root / "pyproject.toml"
    init = root / "reducio/__init__.py"
    project_text = project.read_text()
    old_version = tomllib.loads(project_text)["project"]["version"]
    project_text, project_count = re.subn(
        rf'^version = "{re.escape(old_version)}"$',
        f'version = "{version}"',
        project_text,
        flags=re.MULTILINE,
    )
    init_text, init_count = re.subn(
        r'^__version__ = "[^"]+"$',
        f'__version__ = "{version}"',
        init.read_text(),
        flags=re.MULTILINE,
    )
    if project_count != 1 or init_count != 1:
        raise ValueError("Expected one project version and one __version__ declaration")
    project.write_text(project_text)
    init.write_text(init_text)
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    args = parser.parse_args()
    print(f"Release package version: {stamp_version(Path.cwd(), args.tag)}")
