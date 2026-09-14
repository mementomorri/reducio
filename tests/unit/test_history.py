"""Historical metrics are rebuilt from immutable Git blobs with visible gaps."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reducio.cli import _get_cfg, app
from reducio.compare import CompareError
from reducio.history import _read_blobs, history_revisions, snapshot_metrics
from reducio.models import AppConfig
from reducio.visual_report import ReportFormat, write_reports
from tests.unit.test_compare import commit, git


def test_history_alias_gaps_reuse_and_unchanged_worktree(temp_git_repo, monkeypatch):
    root = temp_git_repo
    first = commit(root, {"old/a.py": "def f(x):\n    if x: return 1\n    return 0\n"})
    commit(root, {"README.md": "no source changes"})
    git(root, "mv", "old", "src")
    git(root, "commit", "-m", "rename root")
    last = commit(root, {"src/a.py": "def f(x):\n    return bool(x)\n"})
    (root / "src/a.py").write_text("dirty, never read")
    status = git(root, "status", "--porcelain")
    cfg = AppConfig(
        history_path_aliases=["old"], complexity_thresholds={"cyclomatic_complexity": 2}
    )
    measured = []
    from reducio import history

    original = history.analyze_files

    def spy(files, *args, **kwargs):
        measured.extend(files)
        return original(files, *args, **kwargs)

    monkeypatch.setattr(history, "analyze_files", spy)
    result = history_revisions(str(root / "src"), cfg=cfg)
    assert result.ref_revision == last and result.head_complete and not result.complete
    assert result.snapshots[1].revision == first
    assert result.snapshots[0].actual_scope is None
    assert result.unique_blobs_analyzed == len(measured) == 2
    assert [s.actual_scope for s in result.snapshots[1:]] == ["old", "old", "src", "src"]
    assert all(f.file == "src/a.py" for s in result.snapshots for f in s.measurement.functions)
    assert result.snapshots[-2].notes and result.snapshots[-2].changes[0].status == "unchanged"
    assert result.snapshots[-1].changes[0].status == "improved"
    assert snapshot_metrics(result.snapshots[-1])["resolved_hotspots"] == 1
    assert snapshot_metrics(result.snapshots[0]) == {}
    assert snapshot_metrics(result.snapshots[1])["new_hotspots"] is None
    assert git(root, "status", "--porcelain") == status
    assert git(root, "rev-parse", "HEAD") == last


def test_history_first_parent_limit_and_current_configuration(temp_git_repo):
    root = temp_git_repo
    branch = git(root, "branch", "--show-current")
    git(root, "checkout", "-b", "feature")
    feature = commit(root, {"a.py": "def a(): pass\n"})
    git(root, "checkout", branch)
    git(root, "merge", "--no-ff", "feature", "-m", "merge")
    result = history_revisions(str(root), cfg=AppConfig(history_limit=2))
    assert len(result.snapshots) == 2
    assert feature not in [s.revision for s in result.snapshots]
    assert result.snapshots[-1].comparison_available
    assert snapshot_metrics(result.snapshots[0])["p95_cc"] is None
    assert snapshot_metrics(result.snapshots[-1])["p95_cc"] == 1
    assert result.configuration["include_patterns"] == ["*.py"]


def test_history_invalid_old_source_gaps_not_false_improvement(temp_git_repo):
    root = temp_git_repo
    commit(root, {"bad.py": "return 1\n"})
    commit(root, {"bad.py": "def f(): pass\n"})
    result = history_revisions(str(root))
    assert not result.snapshots[-2].measurement.complete
    assert result.head_complete and not result.complete
    assert not result.snapshots[-1].changes
    assert snapshot_metrics(result.snapshots[-1])["new_hotspots"] is None


def test_history_decoding_symlinks_and_exclusions(temp_git_repo):
    root = temp_git_repo
    (root / "bad.py").write_bytes(b"\xff\xff")
    (root / "good.py").write_bytes(b'# coding: latin-1\r\ndef f(): return "caf\xe9"\r\n')
    (root / "link.py").symlink_to("/etc/passwd")
    commit(root, {"excluded.py": "broken(\n"})
    result = history_revisions(
        str(root), cfg=AppConfig(history_limit=1, exclude_patterns=["excluded.py"])
    )
    snapshot = result.snapshots[0]
    assert not result.head_complete
    assert {d.file for d in snapshot.measurement.diagnostics} == {"bad.py", "link.py"}
    assert any(f.file == "good.py" for f in snapshot.measurement.functions)


@pytest.mark.parametrize("alias", ["../outside", "/tmp", "", "foo\\bar"])
def test_history_alias_validation(temp_git_repo, alias):
    with pytest.raises(ValueError, match="repository-relative"):
        history_revisions(str(temp_git_repo), cfg=AppConfig(history_path_aliases=[alias]))


def test_shallow_and_missing_ref_are_actionable(temp_git_repo, tmp_path):
    clone = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--depth=1", temp_git_repo.as_uri(), str(clone)],
        check=True,
        capture_output=True,
    )
    with pytest.raises(CompareError, match="full Git history"):
        history_revisions(str(clone))
    with pytest.raises(CompareError):
        history_revisions(str(temp_git_repo), "missing-ref")


@pytest.mark.parametrize("response", [b"missing\n", b"abc blob 9\nshort\n"])
def test_batch_read_failure_is_not_a_historical_gap(tmp_path, monkeypatch, response):
    monkeypatch.setattr("reducio.history._git", lambda *args, **kw: response)
    with pytest.raises(CompareError):
        list(_read_blobs(tmp_path, ["abc"]))


def test_reports_and_cli_history_policy(temp_git_repo, tmp_path):
    root = temp_git_repo
    commit(root, {"a.py": "def broken(:"})
    commit(root, {"a.py": "def f(): return 1\n"})
    output = tmp_path / "reports"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "history",
            str(root),
            "--report",
            "--format",
            "all",
            "--output-dir",
            str(output),
            "--quiet",
        ],
    )
    assert result.exit_code == 0, result.output
    files = {p.suffix: p for p in output.iterdir()}
    data = json.loads(files[".json"].read_text())
    assert data["head_complete"] and not data["complete"]
    assert "GAP" in files[".md"].read_text()
    html = files[".html"].read_text()
    assert 'id="history-function"' in html and 'id="chart-0"' in html
    assert not re.search(r"<script\b[^>]*\bsrc\s*=", html)
    script = Path(__file__).resolve().parents[2] / "reducio/history_view.js"
    assert "fetch(" not in script.read_text()
    commit(root, {"a.py": "break\n"})
    assert runner.invoke(app, ["history", str(root), "--quiet"]).exit_code == 1
    assert runner.invoke(app, ["history", str(root), "--ref", "absent", "--quiet"]).exit_code == 1
    assert (
        runner.invoke(app, ["history", str(root), "--path-alias", "../bad", "--quiet"]).exit_code
        == 2
    )
    assert runner.invoke(app, ["history", str(root), "--limit", "0"]).exit_code == 2


def test_history_limit_precedence_and_html_escape(temp_git_repo, tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("history_limit: 2\nhistory_path_aliases: [old]\n")
    assert _get_cfg(config).history_limit == 2
    monkeypatch.setenv("REDUCIO_HISTORY_LIMIT", "3")
    assert _get_cfg(config).history_limit == 3
    assert _get_cfg(config, history_limit=1).history_limit == 1
    result = history_revisions(str(temp_git_repo), cfg=AppConfig(history_limit=1))
    result.snapshots[0].subject = '</script><script>alert("unsafe")</script>'
    files = write_reports(result, tmp_path / "out", ReportFormat.ALL)
    html = files[-1].read_text()
    assert "</script><script>alert(" not in html
    payload = html.split('id="history-data" type="application/json">', 1)[1].split("</script>", 1)[
        0
    ]
    assert json.loads(payload)["snapshots"][0]["subject"] == result.snapshots[0].subject
    assert Path(__file__).resolve().parents[2].joinpath("reducio/history_view.js").exists()


def test_default_100_commit_limit_reuses_blobs(temp_git_repo):
    root = temp_git_repo
    commit(root, {"a.py": "def f(): return 1\n"})
    for index in range(100):
        git(root, "commit", "--allow-empty", "-m", f"docs {index}")
    result = history_revisions(str(root))
    assert len(result.snapshots) == result.limit == 100
    assert result.unique_blobs_analyzed == 2 and result.complete  # a.py plus fixture main.py
    assert all(s.changes[0].status == "unchanged" for s in result.snapshots[1:])


def test_batches_exceeding_128_blobs_and_nearest_rank(temp_git_repo):
    commit(temp_git_repo, {f"file{i}.py": f"def f(): return {i}\n" for i in range(130)})
    result = history_revisions(
        str(temp_git_repo), cfg=AppConfig(history_limit=1, exclude_patterns=["main.py"])
    )
    assert result.unique_blobs_analyzed == 130 and result.complete
    assert snapshot_metrics(result.snapshots[0])["p95_cc"] == 1
    for index, function in enumerate(result.snapshots[0].measurement.functions):
        function.cyclomatic_complexity = index + 1
    scores = snapshot_metrics(result.snapshots[0])
    assert scores["median_cc"] == 65.5 and scores["p95_cc"] == 124


def test_empty_history_html_fails_cleanly(temp_git_repo, tmp_path):
    from reducio.visual_report import ReportError

    result = history_revisions(str(temp_git_repo))
    result.snapshots.clear()
    assert not result.head_complete and not result.complete
    with pytest.raises(ReportError, match="no snapshots"):
        write_reports(result, tmp_path / "out", ReportFormat.HTML)


def test_history_dashboard_interaction_without_external_runtime(temp_git_repo, tmp_path):
    if not shutil.which("node"):
        pytest.skip("Node is needed for the dependency-free dashboard interaction check")
    root = temp_git_repo
    commit(root, {"a.py": "def f():\n    if x: return 1\n    return 0\n"})
    commit(root, {"a.py": "def broken(:"})
    commit(root, {"a.py": "def f(): return 1\n"})
    result = history_revisions(
        str(root),
        cfg=AppConfig(
            include_patterns=["a.py"], complexity_thresholds={"cyclomatic_complexity": 2}
        ),
    )
    from reducio.history_report import html_history

    html = html_history(result)
    data = html.split('id="history-data" type="application/json">', 1)[1].split("</script>", 1)[0]
    payload = tmp_path / "history.json"
    payload.write_text(data)
    check = Path(__file__).resolve().parents[1] / "history_view_smoke.js"
    subprocess.run(["node", str(check), str(payload)], check=True, capture_output=True, text=True)
