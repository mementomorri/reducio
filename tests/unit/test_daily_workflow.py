"""Opt-in working-file comparisons, actionable PR policy and quality controls."""

import json

import pytest
from typer.testing import CliRunner

from reducio.annotations import github_annotations
from reducio.cli import app
from reducio.compare import compare_revisions
from reducio.models import AppConfig, FileInfo
from reducio.services import App
from tests.unit.test_compare import commit, git


def test_against_uses_merge_base_not_moving_main(temp_git_repo):
    root = temp_git_repo
    branch = git(root, "branch", "--show-current")
    base = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "-b", "feature")
    feature = commit(root, {"feature.py": "def f(): pass\n"})
    git(root, "checkout", branch)
    commit(root, {"unrelated.py": "def other(): pass\n"})
    git(root, "checkout", "feature")
    result = compare_revisions(str(root), against=branch)
    assert result.base_revision == base and result.head_revision == feature
    assert [f["after"] for f in result.files] == ["feature.py"]


def test_worktree_includes_current_staged_untracked_deleted_not_ignored(temp_git_repo):
    root = temp_git_repo
    base = commit(
        root,
        {
            "a.py": "def f(): return 0\n",
            "deleted.py": "def gone(): pass\n",
            ".gitignore": "ignored.py\n",
        },
    )
    (root / "a.py").write_text("def f():\n    if x: return 1\n    return 0\n")
    git(root, "add", "a.py")
    (root / "a.py").write_text("def f():\n    if x:\n        if y: return 1\n    return 0\n")
    (root / "deleted.py").unlink()
    (root / "new.py").write_text("def new(): pass\n")
    (root / "ignored.py").write_text("broken(\n")
    status = git(root, "status", "--porcelain")
    result = compare_revisions(str(root), base, worktree=True)
    assert result.head_source == "worktree" and result.head_revision == base
    assert result.counts["regressed"] == result.counts["added"] == result.counts["removed"] == 1
    assert result.after.functions[0].cyclomatic_complexity == 3
    assert "WORKTREE" in result.notes[-1]
    assert git(root, "status", "--porcelain") == status
    assert compare_revisions(str(root), base).files == []
    (root / "new.py").write_text("return 1\n")
    assert not compare_revisions(str(root), base, worktree=True).complete


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--base", "HEAD", "--against", "HEAD"],
        ["--against", "HEAD", "--head", "HEAD"],
        ["--base", "HEAD", "--worktree", "--head", "HEAD"],
        ["--base", "HEAD", "--annotations", "unknown"],
        ["--base", "HEAD", "--fail-on", "unknown"],
    ],
)
def test_conflicting_cli_comparison_options(temp_git_repo, args):
    result = CliRunner().invoke(app, ["compare", str(temp_git_repo), *args])
    assert result.exit_code == 2, result.output


@pytest.mark.parametrize(
    "gate,failed", [("none", False), ("new-hotspots", False), ("regressions", True)]
)
def test_comparison_gates_report_before_exit(temp_git_repo, tmp_path, gate, failed):
    root = temp_git_repo
    base = commit(root, {"a.py": "def f(): return 0\n"})
    commit(root, {"a.py": "def f():\n    if x: return 1\n    return 0\n"})
    output = tmp_path / "reports"
    result = CliRunner().invoke(
        app,
        [
            "compare",
            str(root),
            "--base",
            base,
            "--fail-on",
            gate,
            "--annotations",
            "github",
            "--report",
            "--format",
            "all",
            "--output-dir",
            str(output),
            "--quiet",
        ],
    )
    assert result.exit_code == int(failed), result.output
    assert "::warning file=a.py,line=1" in result.output
    data = json.loads(next(output.glob("*.json")).read_text())
    assert data["gate_failed"] is failed and data["gate_threshold"] == gate
    assert gate in next(output.glob("*.md")).read_text()


def test_new_hotspots_mixed_regressions_and_existing_debt(temp_git_repo):
    root = temp_git_repo
    source = "def f():\n    if a: pass\n    if b: pass\n    if c: pass\n    if d: pass\n"
    debt = "\ndef existing():\n    if x: pass\n"
    base = commit(root, {"a.py": source + debt})
    # Decrease CC but increase cognitive score: mixed is a regression gate failure.
    commit(root, {"a.py": "def f():\n    if a:\n        if b:\n            if c: pass\n" + debt})
    cfg = AppConfig(
        compare_fail_on="new-hotspots", complexity_thresholds={"cyclomatic_complexity": 2}
    )
    result = compare_revisions(str(root), base, cfg=cfg)
    assert not result.gate_failed and result.counts["mixed"] == result.counts["unchanged"] == 1
    cfg.compare_fail_on = "regressions"
    assert compare_revisions(str(root), base, cfg=cfg).gate_failed
    cfg.compare_fail_on = "new-hotspots"
    commit(root, {"new.py": "def new():\n    if x: pass\n"})
    result = compare_revisions(str(root), base, cfg=cfg)
    assert result.gate_failed and result.counts["new_hotspots"] == 1
    assert not compare_revisions(str(root), "HEAD", cfg=cfg).gate_failed


def test_worktree_staged_rename_subdirectory_and_unreadable_file(temp_git_repo):
    root = temp_git_repo
    base = commit(root, {"src/a.py": "def f(): return 0\n", "outside.py": "def other(): pass\n"})
    git(root, "mv", "src/a.py", "src/renamed.py")
    (root / "outside.py").write_text("break\n")
    result = compare_revisions(str(root / "src"), base, worktree=True)
    assert result.complete and len(result.changes) == 1
    assert result.changes[0].status == "unchanged"
    assert result.after.functions[0].file == "src/renamed.py"
    (root / "src/link.py").symlink_to("/etc/passwd")
    result = compare_revisions(str(root / "src"), base, worktree=True)
    assert not result.complete and result.after.diagnostics[0].file == "src/link.py"


def test_worktree_staged_deletion_with_recreated_file_is_one_change(temp_git_repo):
    root = temp_git_repo
    base = commit(root, {"a.py": "def f(): return 0\n"})
    git(root, "rm", "--cached", "a.py")
    (root / "a.py").write_text("def f():\n    if x: return 1\n    return 0\n")
    status = git(root, "status", "--porcelain")
    result = compare_revisions(str(root), base, worktree=True)
    assert result.files == [{"status": "M", "before": "a.py", "after": "a.py"}]
    assert result.counts["regressed"] == 1 and len(result.changes) == 1
    assert git(root, "status", "--porcelain") == status


def test_annotations_escape_and_cap(temp_git_repo):
    root = temp_git_repo
    base = git(root, "rev-parse", "HEAD")
    commit(root, {f"f{i}.py": f"def function_{i}():\n    if x: pass\n" for i in range(12)})
    result = compare_revisions(
        str(root), base, cfg=AppConfig(complexity_thresholds={"cyclomatic_complexity": 2})
    )
    result.changes[0].after.file = "unsafe,colon:\n::error%file.py"
    result.changes[0].after.qualified_name = "unsafe\r\n::error::spoof%"
    messages = github_annotations(result)
    assert len(messages) == 10 and all("\n" not in m and "\r" not in m for m in messages)
    result.changes = result.changes[:1]
    assert "%2C" in github_annotations(result)[0] and "%0A" in github_annotations(result)[0]


async def test_quality_overrides_and_targeted_suppressions(tmp_path):
    cfg = AppConfig(
        quality_rules={"naming_convention": "off", "bad_variable_name": "info"},
        quality_ignores={"tests/*.py": ["bad_variable_name"]},
    )
    service = App(str(tmp_path), cfg)
    files = [
        FileInfo(path=p, content="def BAD():\n    zz = 1\n") for p in ("src/a.py", "tests/a.py")
    ]
    files.append(FileInfo(path="tests/bad.py", content="break\n"))
    result = (await service.quality.check_quality(files, ".")).to_dict()
    assert result["suppressed_count"] == 3
    assert len(result["issues"]) == 2
    assert (
        next(i for i in result["issues"] if i["issue_type"] == "bad_variable_name")["severity"]
        == "info"
    )
    assert any(i["issue_type"] == "parse_error" for i in result["issues"])
    from reducio.reporter import Reporter

    report = Reporter(output_dir=tmp_path).generate_check(result).read_text()
    assert "Suppressed findings" in report and "quality_ignores" in report


@pytest.mark.parametrize(
    "settings",
    [
        {"quality_rules": {"parse_error": "off"}},
        {"quality_rules": {"typo": "off"}},
        {"quality_ignores": {"*.py": ["parse_error"]}},
    ],
)
def test_bad_or_unsafe_rules_cannot_be_configured(settings):
    with pytest.raises(ValueError):
        AppConfig.model_validate(settings)


def test_quality_cli_suppression_and_compare_env(temp_git_repo, tmp_path, monkeypatch):
    (temp_git_repo / "a.py").write_text("zz = 1\n")
    config = tmp_path / "settings.yaml"
    config.write_text("quality_rules:\n  bad_variable_name: off\ncompare_fail_on: new-hotspots\n")
    # Quote 'off': YAML 1.1 otherwise reads it as a boolean, which is rejected.
    config.write_text(config.read_text().replace(": off", ': "off"'))
    result = CliRunner().invoke(
        app,
        ["check", str(temp_git_repo), "--config", str(config), "--fail-on", "warning", "--quiet"],
    )
    assert result.exit_code == 0 and "Suppressed findings: 1" in result.output
    monkeypatch.setenv("REDUCIO_COMPARE_FAIL_ON", "regressions")
    from reducio.cli import _get_cfg

    assert _get_cfg(config).compare_fail_on == "regressions"
    assert _get_cfg(config, compare_fail_on="none").compare_fail_on == "none"
