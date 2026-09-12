"""Identify a published wheel and attach its PyApp executable to the existing tag."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import zipfile
from email.parser import BytesParser
from pathlib import Path

from packaging.utils import canonicalize_name
from packaging.version import Version


def package_metadata(wheel_directory: Path, commit: str) -> dict[str, str]:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Expected the full lowercase commit SHA")
    # Downloaded artifacts are in directories named for their workflow attempt.
    # If all jobs were rerun, use the wheel from the newest publishing attempt.
    attempts = list(wheel_directory.glob("published-wheel-*"))
    if attempts:
        wheel_directory = max(attempts, key=lambda path: int(path.name.rsplit("-", 1)[1]))
    wheels = list(wheel_directory.glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError(f"Expected exactly one published wheel, found {len(wheels)}")
    wheel = wheels[0].resolve()
    with zipfile.ZipFile(wheel) as archive:
        metadata_files = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
        if len(metadata_files) != 1:
            raise ValueError("Expected exactly one wheel METADATA file")
        metadata = BytesParser().parsebytes(archive.read(metadata_files[0]))
    if canonicalize_name(metadata["Name"]) != "reducio":
        raise ValueError("The published wheel must contain reducio")
    version = Version(metadata["Version"])
    return {
        "wheel": str(wheel),
        "commit": commit,
        "version": str(version),
        "prerelease": str(version.is_prerelease or version.is_devrelease).lower(),
    }


def release_metadata(wheel_directory: Path, commit: str, tag: str) -> dict[str, str]:
    # The tag becomes a filename and a download pattern; exclude path separators,
    # glob characters and whitespace rather than silently changing the tag.
    if not re.fullmatch(r"v[A-Za-z0-9][A-Za-z0-9._+-]*", tag):
        raise ValueError("Expected a filename-safe v* publishing tag")
    return {
        **package_metadata(wheel_directory, commit),
        "tag": tag,
        "release_name": f"reducio-{tag}",
        "binary_name": f"reducio-{tag}",
    }


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def find_release(repo: str, tag: str) -> dict | None:
    # The by-tag REST endpoint cannot find pending draft tags. The authenticated
    # list includes drafts; paginate so older releases can also be resumed.
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/releases?per_page=100"))
    return next((release for page in pages for release in page if release["tag_name"] == tag), None)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def release_notes(package: dict[str, str]) -> str:
    binary = package["binary_name"]
    return f"""Linux x64 executable for Reducio {package['version']}.

Commit: {package['commit']}

Includes HTML reports and semantic embeddings (`reports,embeddings,llm`). Built with
PyApp 0.29.0 on Ubuntu 22.04 for Linux x64 with glibc; Alpine/musl is not supported.
The executable embeds the same Reducio wheel published to PyPI by this workflow.

Download `{binary}` and `{binary}.sha256` into the same directory, then run:

```bash
sha256sum --check {binary}.sha256
chmod +x {binary}
./{binary} --help
./{binary} analyze . --report --format all
```

Python 3.14 and package dependencies are downloaded and installed on first launch.
The embedding model is downloaded on first use. Internet access and writable user
storage are required for initial setup; this is not an offline bundle.
Git operations require Git on PATH. Target-project tests still require their own
configured environment. Download a newer executable to upgrade; PyApp management
commands are disabled. `version` reports the Python package version.
"""


def publish(package: dict[str, str], tag: str, repo: str, asset_directory: Path) -> str:
    if package["tag"] != tag:
        raise ValueError("Release metadata must match the publishing tag")
    binary = asset_directory / package["binary_name"]
    if not binary.is_file() or binary.stat().st_size == 0 or not binary.stat().st_mode & 0o111:
        raise ValueError(f"Missing or non-executable release binary: {binary}")
    checksum = binary.with_name(binary.name + ".sha256")
    checksum.write_text(f"{digest(binary)}  {binary.name}\n")
    assets = [binary, checksum]
    release = find_release(repo, tag)
    with tempfile.TemporaryDirectory(prefix="reducio-release-") as temporary:
        staging = Path(temporary)
        if release is None:
            notes = staging / "notes.md"
            notes.write_text(release_notes(package))
            gh(
                "release",
                "create",
                tag,
                "--repo",
                repo,
                "--verify-tag",
                "--draft",
                "--title",
                package["release_name"],
                "--notes-file",
                str(notes),
                f"--prerelease={package['prerelease']}",
            )
            release = find_release(repo, tag)
            if release is None:
                raise RuntimeError("The newly created draft release could not be found")

        existing = {asset["name"] for asset in release["assets"]}
        missing = []
        # Check every existing asset before uploading anything. Never replace bytes.
        for asset in assets:
            if asset.name not in existing:
                missing.append(asset)
                continue
            gh(
                "release",
                "download",
                tag,
                "--repo",
                repo,
                "--pattern",
                asset.name,
                "--dir",
                str(staging),
            )
            if digest(staging / asset.name) != digest(asset):
                raise ValueError(
                    f"Release asset {asset.name} already exists with different contents"
                )
        if missing:
            gh("release", "upload", tag, *(str(asset) for asset in missing), "--repo", repo)
        gh(
            "release",
            "edit",
            tag,
            "--repo",
            repo,
            "--title",
            package["release_name"],
            f"--prerelease={package['prerelease']}",
            "--draft=false",
        )
    published = find_release(repo, tag)
    if published is None or published["draft"]:
        raise RuntimeError("The release was not published successfully")
    return published["html_url"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    metadata_parser = commands.add_parser("metadata")
    publish_parser = commands.add_parser("publish")
    for command in (metadata_parser, publish_parser):
        command.add_argument("--wheel-directory", required=True, type=Path)
        command.add_argument("--commit", required=True)
        command.add_argument("--tag", required=True)
    metadata_parser.add_argument("--output", required=True, type=Path)
    publish_parser.add_argument("--repo", required=True)
    publish_parser.add_argument("--asset-directory", required=True, type=Path)
    publish_parser.add_argument("--summary", required=True, type=Path)
    args = parser.parse_args()
    package = release_metadata(args.wheel_directory, args.commit, args.tag)
    if args.command == "metadata":
        with args.output.open("a") as output:
            for key, value in package.items():
                if "\n" in value or "\r" in value:
                    raise ValueError("Workflow output must be a single line")
                output.write(f"{key}={value}\n")
    else:
        url = publish(package, args.tag, args.repo, args.asset_directory)
        with args.summary.open("a") as summary:
            summary.write(
                f"Published [{package['release_name']}]({url})\n\n"
                f"- `{package['binary_name']}`\n- `{package['binary_name']}.sha256`\n"
            )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.stderr or str(error)) from error
