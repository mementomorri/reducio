"""Release retries must preserve published bytes and unrelated release content."""

import json
import subprocess
import zipfile
from pathlib import Path

import pytest
import yaml

from scripts import pyapp_release

COMMIT = "abcdef1234567890abcdef1234567890abcdef12"


def make_wheel(directory, version="1.2.3", name="reducio"):
    directory.mkdir(parents=True, exist_ok=True)
    wheel = directory / f"{name.replace('-', '_')}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            f"{name}-{version}.dist-info/METADATA", f"Name: {name}\nVersion: {version}\n"
        )
    return wheel


@pytest.mark.parametrize(
    "version,prerelease", [("1.2.3", "false"), ("1.3rc1", "true"), ("1.3.dev1", "true")]
)
def test_metadata_names_commit_and_preserves_package_version(tmp_path, version, prerelease):
    wheel = make_wheel(tmp_path, version)
    package = pyapp_release.package_metadata(tmp_path, COMMIT)
    assert package["release_name"] == "reducio-abcdef1"
    assert package["binary_name"] == "reducio-abcdef1-linux-x86_64"
    assert package["version"] == version
    assert package["prerelease"] == prerelease
    assert package["wheel"] == str(wheel.resolve())


def test_rerun_uses_latest_publishing_attempt(tmp_path):
    make_wheel(tmp_path / "published-wheel-2", "1.0.0")
    wheel = make_wheel(tmp_path / "published-wheel-10", "2.0.0")
    assert pyapp_release.package_metadata(tmp_path, COMMIT)["wheel"] == str(wheel)


def test_rejects_ambiguous_or_wrong_wheels(tmp_path):
    with pytest.raises(ValueError, match="exactly one"):
        pyapp_release.package_metadata(tmp_path, COMMIT)
    make_wheel(tmp_path, name="another")
    with pytest.raises(ValueError, match="must contain reducio"):
        pyapp_release.package_metadata(tmp_path, COMMIT)
    make_wheel(tmp_path)
    with pytest.raises(ValueError, match="exactly one"):
        pyapp_release.package_metadata(tmp_path, COMMIT)


@pytest.mark.parametrize("commit", ["abcdef1", "x" * 40, COMMIT + "\n"])
def test_rejects_invalid_commit(tmp_path, commit):
    with pytest.raises(ValueError, match="full lowercase commit"):
        pyapp_release.package_metadata(tmp_path, commit)


class FakeGitHub:
    def __init__(self, release=None, assets=None):
        self.release = release
        self.assets = assets or {}
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        if args[0] == "api":
            assert "--paginate" in args and "--slurp" in args
            if self.release is None:
                return "[[]]"
            return json.dumps(
                [
                    [
                        {
                            **self.release,
                            "tag_name": "v1.2.3",
                            "assets": [{"name": name} for name in self.assets],
                        }
                    ]
                ]
            )
        command = args[1]
        if command == "create":
            assert "--verify-tag" in args and "--draft" in args
            self.release = {
                "html_url": "https://github.com/owner/repo/releases/tag/untagged-draft",
                "draft": True,
                "body": Path(args[args.index("--notes-file") + 1]).read_text(),
            }
        elif command == "download":
            name = args[args.index("--pattern") + 1]
            (Path(args[args.index("--dir") + 1]) / name).write_bytes(self.assets[name])
        elif command == "upload":
            assert "--clobber" not in args
            for filename in args[3 : args.index("--repo")]:
                asset = Path(filename)
                self.assets[asset.name] = asset.read_bytes()
        elif command == "edit":
            self.release["draft"] = False
            self.release["html_url"] = self.release["html_url"].replace("untagged-draft", "v1.2.3")
            assert "--notes-file" not in args and "--notes" not in args
        else:
            raise AssertionError(args)
        return ""


@pytest.fixture
def package_and_binary(tmp_path):
    make_wheel(tmp_path)
    package = pyapp_release.package_metadata(tmp_path, COMMIT)
    binary = tmp_path / package["binary_name"]
    binary.write_bytes(b"a tested executable")
    binary.chmod(0o755)
    return package, binary


def test_new_release_publishes_only_after_upload_and_retry_skips_assets(
    monkeypatch, package_and_binary
):
    package, binary = package_and_binary
    github = FakeGitHub()
    monkeypatch.setattr(pyapp_release, "gh", github)
    url = pyapp_release.publish(package, "v1.2.3", "owner/repo", binary.parent)
    assert url == github.release["html_url"]
    assert github.release["draft"] is False
    assert COMMIT in github.release["body"]
    checksum_name = binary.name + ".sha256"
    assert (
        github.assets[checksum_name] == f"{pyapp_release.digest(binary)}  {binary.name}\n".encode()
    )
    subprocess.run(
        ["sha256sum", "--check", checksum_name], cwd=binary.parent, check=True, capture_output=True
    )
    assert [call[1] for call in github.calls if call[0] == "release"] == [
        "create",
        "upload",
        "edit",
    ]
    github.calls.clear()
    pyapp_release.publish(package, "v1.2.3", "owner/repo", binary.parent)
    assert not any(call[1] in {"create", "upload"} for call in github.calls)


def test_partial_draft_retry_preserves_notes_and_unrelated_assets(monkeypatch, package_and_binary):
    package, binary = package_and_binary
    github = FakeGitHub(
        {"html_url": "https://example.test/release", "draft": True, "body": "Handwritten notes"},
        {binary.name: binary.read_bytes(), "other.zip": b"keep me"},
    )
    monkeypatch.setattr(pyapp_release, "gh", github)
    pyapp_release.publish(package, "v1.2.3", "owner/repo", binary.parent)
    assert github.release["body"] == "Handwritten notes"
    assert github.assets["other.zip"] == b"keep me"
    upload = next(call for call in github.calls if call[:2] == ("release", "upload"))
    assert upload[3 : upload.index("--repo")] == (str(binary) + ".sha256",)


def test_upload_failure_keeps_draft_for_retry(monkeypatch, package_and_binary):
    package, binary = package_and_binary
    github = FakeGitHub()

    def interrupted_upload(*args):
        if args[:2] == ("release", "upload"):
            github.assets[binary.name] = binary.read_bytes()
            raise subprocess.CalledProcessError(1, args, stderr="upload interrupted")
        return github(*args)

    monkeypatch.setattr(pyapp_release, "gh", interrupted_upload)
    with pytest.raises(subprocess.CalledProcessError, match="non-zero exit"):
        pyapp_release.publish(package, "v1.2.3", "owner/repo", binary.parent)
    assert github.release["draft"] is True
    assert not any(call[:2] == ("release", "edit") for call in github.calls)
    monkeypatch.setattr(pyapp_release, "gh", github)
    pyapp_release.publish(package, "v1.2.3", "owner/repo", binary.parent)
    assert github.release["draft"] is False
    assert len(github.assets) == 2


@pytest.mark.parametrize("conflicting_asset", ["binary", "checksum"])
def test_conflicting_asset_fails_before_any_release_mutation(
    monkeypatch, package_and_binary, conflicting_asset
):
    package, binary = package_and_binary
    name = binary.name + (".sha256" if conflicting_asset == "checksum" else "")
    github = FakeGitHub(
        {"html_url": "https://example.test/release", "draft": False}, {name: b"different"}
    )
    monkeypatch.setattr(pyapp_release, "gh", github)
    with pytest.raises(ValueError, match="different contents"):
        pyapp_release.publish(package, "v1.2.3", "owner/repo", binary.parent)
    assert all(call[0] == "api" or call[1] == "download" for call in github.calls)
    assert github.assets[name] == b"different"


@pytest.mark.parametrize("message", ["HTTP 403", "HTTP 404", "HTTP 429", "connection refused"])
def test_lookup_errors_do_not_create_release(monkeypatch, package_and_binary, message):
    package, binary = package_and_binary
    calls = []

    def failing_gh(*args):
        calls.append(args)
        raise subprocess.CalledProcessError(1, args, stderr=message)

    monkeypatch.setattr(pyapp_release, "gh", failing_gh)
    with pytest.raises(subprocess.CalledProcessError):
        pyapp_release.publish(package, "v1.2.3", "owner/repo", binary.parent)
    assert len(calls) == 1 and calls[0][0] == "api"


def test_lookup_finds_draft_on_later_page(monkeypatch):
    draft = {"tag_name": "v1.2.3", "draft": True}
    monkeypatch.setattr(
        pyapp_release,
        "gh",
        lambda *args: json.dumps(
            [
                [{"tag_name": "v2.0.0", "draft": False}],
                [draft],
            ]
        ),
    )
    assert pyapp_release.find_release("owner/repo", "v1.2.3") == draft
    assert pyapp_release.find_release("owner/repo", "v3.0.0") is None


def test_publish_workflow_gates_release_and_limits_credentials():
    workflow = Path(__file__).resolve().parents[2] / ".github/workflows/publish.yml"
    document = yaml.safe_load(workflow.read_text())
    assert document["concurrency"]["cancel-in-progress"] is False
    jobs = document["jobs"]
    assert jobs["pyapp"]["needs"] == ["pypi", "verify-pypi"]
    assert jobs["verify-pypi"]["needs"] == "pypi"
    assert jobs["pyapp"]["permissions"] == {"contents": "write"}
    assert jobs["pypi"]["permissions"]["id-token"] == "write"
    steps = jobs["pyapp"]["steps"]
    assert not any(
        "always()" in step.get("if", "") or step.get("continue-on-error") for step in steps
    )
    smoke_index = next(
        i for i, step in enumerate(steps) if "scripts/smoke_pyapp.py" in step.get("run", "")
    )
    release_index = next(
        i for i, step in enumerate(steps) if "pyapp_release.py publish" in step.get("run", "")
    )
    assert smoke_index < release_index
    assert all("GH_TOKEN" not in step.get("env", {}) for step in steps[:release_index])
