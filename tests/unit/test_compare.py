"""Revision comparison against isolated Git histories, including dirty worktrees."""

import subprocess

import pytest

from reducto.compare import CompareError, compare_revisions
from reducto.models import AppConfig


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def commit(root, files):
    for path, content in files.items():
        target = root / path
        if content is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
    git(root, "add", "-A")
    git(root, "commit", "-m", "sample revision")
    return git(root, "rev-parse", "HEAD")


def test_compare_full_functions_and_preserve_worktree(temp_git_repo):
    base = commit(
        temp_git_repo, {"main.py": "def f(x):\n    if x:\n        return 1\n    return 0\n"}
    )
    head = commit(temp_git_repo, {"main.py": "def f(x):\n    return int(bool(x))\n"})
    (temp_git_repo / "main.py").write_text("do not read or change me")
    git(temp_git_repo, "add", "main.py")
    (temp_git_repo / "main.py").write_text("unstaged content")
    (temp_git_repo / "untracked.py").write_text("also untouched")
    status = git(temp_git_repo, "status", "--porcelain")
    result = compare_revisions(str(temp_git_repo), base, head)
    assert result.complete
    assert result.base_revision == base and result.head_revision == head
    assert result.changes[0].status == "improved"
    assert result.changes[0].cyclomatic_delta == -1
    assert result.changes[0].lines_delta == -2
    assert git(temp_git_repo, "status", "--porcelain") == status
    assert git(temp_git_repo, "rev-parse", "HEAD") == head
    assert (temp_git_repo / "main.py").read_text() == "unstaged content"


def test_additions_deletions_and_threshold_crossings(temp_git_repo):
    base = commit(
        temp_git_repo,
        {"old.py": "def old():\n    return 0\n", "main.py": "def f():\n    return 1\n"},
    )
    commit(
        temp_git_repo,
        {
            "old.py": None,
            "new.py": "def new():\n    return 2\n",
            "main.py": "def f():\n    if x:\n        return 1\n",
        },
    )
    result = compare_revisions(
        str(temp_git_repo), base, cfg=AppConfig(complexity_thresholds={"cyclomatic_complexity": 2})
    )
    assert result.counts["added"] == result.counts["removed"] == result.counts["regressed"] == 1
    assert result.counts["new_hotspots"] == 1
    assert next(c for c in result.changes if c.status == "added").cyclomatic_delta is None


def test_file_rename_keeps_function_identity(temp_git_repo):
    base = commit(temp_git_repo, {"original.py": "def stable():\n    return 1\n"})
    git(temp_git_repo, "mv", "original.py", "renamed.py")
    git(temp_git_repo, "commit", "-m", "rename")
    result = compare_revisions(str(temp_git_repo), base)
    assert len(result.changes) == 1
    assert result.changes[0].status == "unchanged"
    assert result.changes[0].before.file == "original.py"
    assert result.changes[0].after.file == "renamed.py"


def test_scope_and_exclusions(temp_git_repo):
    base = commit(temp_git_repo, {"src/a.py": "def f():\n    pass\n", "tests/t.py": "x=1\n"})
    commit(
        temp_git_repo,
        {
            "src/a.py": "def f():\n    return 1\n",
            "tests/t.py": "x=2\n",
            "src/.hidden.py": "x=1\n",
            "src/venv/x.py": "x=1\n",
        },
    )
    result = compare_revisions(str(temp_git_repo / "src"), base)
    assert [f["after"] for f in result.files] == ["src/a.py"]
    assert result.scope == "src"


def test_empty_and_docs_only_changes(temp_git_repo):
    base = git(temp_git_repo, "rev-parse", "HEAD")
    assert compare_revisions(str(temp_git_repo), base).files == []
    commit(temp_git_repo, {"README.md": "documentation"})
    result = compare_revisions(str(temp_git_repo), base)
    assert result.complete and not result.files and not result.changes


@pytest.mark.parametrize("broken_side", ["base", "head"])
def test_invalid_python_is_not_counted_as_addition_or_removal(temp_git_repo, broken_side):
    valid, invalid = "def f():\n    return 1\n", "def f(:\n"
    base = commit(temp_git_repo, {"main.py": invalid if broken_side == "base" else valid})
    commit(temp_git_repo, {"main.py": invalid if broken_side == "head" else valid})
    result = compare_revisions(str(temp_git_repo), base)
    assert not result.complete and not result.changes
    diagnostics = result.before.diagnostics + result.after.diagnostics
    assert diagnostics[0].revision == (base if broken_side == "base" else result.head_revision)


def test_invalid_revision_and_non_git_target(temp_git_repo, tmp_path):
    with pytest.raises(CompareError):
        compare_revisions(str(temp_git_repo), "missing-ref")
    with pytest.raises(CompareError):
        compare_revisions(str(tmp_path), "HEAD")


def test_ambiguous_functions_and_function_renames_are_not_guessed(temp_git_repo):
    base = commit(
        temp_git_repo, {"main.py": "def f():\n    pass\ndef f():\n    pass\ndef old():\n    pass\n"}
    )
    commit(temp_git_repo, {"main.py": "def f():\n    return 1\ndef new():\n    pass\n"})
    result = compare_revisions(str(temp_git_repo), base)
    assert result.notes
    assert result.counts["added"] == 2 and result.counts["removed"] == 3
    assert result.counts["improved"] == result.counts["regressed"] == 0


def test_non_utf8_source_and_unusual_filename(temp_git_repo):
    base = git(temp_git_repo, "rev-parse", "HEAD")
    path = temp_git_repo / "odd name\nfile.py"
    path.write_bytes(b'# coding: latin-1\ndef f():\n    return "\xe9"\n')
    git(temp_git_repo, "add", "-A")
    git(temp_git_repo, "commit", "-m", "encoded source")
    result = compare_revisions(str(temp_git_repo), base)
    assert result.complete and result.counts["added"] == 1


def test_source_symlink_is_not_followed(temp_git_repo):
    base = git(temp_git_repo, "rev-parse", "HEAD")
    (temp_git_repo / "link.py").symlink_to("/etc/passwd")
    git(temp_git_repo, "add", "-A")
    git(temp_git_repo, "commit", "-m", "symlink")
    result = compare_revisions(str(temp_git_repo), base)
    assert not result.complete
    assert "symlink" in result.after.diagnostics[0].message
