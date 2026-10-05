"""Stamp the CI checkout with the PyPI version requested by a release tag."""

import argparse
import re
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
    # The package version is dynamic: hatch reads it from reducio/__init__.py.
    version = tag_version(tag)
    init = root / "reducio/__init__.py"
    text, count = re.subn(
        r'^__version__ = "[^"]+"$', f'__version__ = "{version}"', init.read_text(), flags=re.M
    )
    if count != 1:
        raise ValueError("Expected one __version__ declaration")
    init.write_text(text)
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    args = parser.parse_args()
    print(f"Release package version: {stamp_version(Path.cwd(), args.tag)}")
