"""The workflow's parser guard must inspect data, not incidental log lines."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize(
    "complete,symbols,functions,valid",
    [
        (True, 1, [{"name": "f"}], True),
        (True, 0, [], False),
        (False, 1, [{"name": "f"}], False),
    ],
)
def test_workflow_structured_parser_guard(
    tmp_path, monkeypatch, complete, symbols, functions, valid
):
    workflow = Path(__file__).resolve().parents[2] / ".github/workflows/analysis.yml"
    jobs = yaml.safe_load(workflow.read_text())["jobs"]
    step = next(
        s for s in jobs["overview"]["steps"] if s.get("name") == "Validate structured result"
    )
    script = step["run"].split("\n", 1)[1].rsplit("\nPY", 1)[0]
    output = tmp_path / "ci-reports/overview"
    output.mkdir(parents=True)
    (output / "sample.json").write_text(
        json.dumps(
            {
                "complete": complete,
                "total_symbols": symbols,
                "functions": functions,
                "total_hotspots": 0,
                "hotspots": [],
            }
        )
    )
    monkeypatch.chdir(tmp_path)
    if valid:
        exec(script, {})
    else:
        with pytest.raises(AssertionError):
            exec(script, {})


def pages_job():
    workflow = Path(__file__).resolve().parents[2] / ".github/workflows/analysis.yml"
    return yaml.safe_load(workflow.read_text())["jobs"]["publish-pages"]


@pytest.mark.parametrize(
    "event,ref,expected",
    [
        ("push", "refs/heads/main", True),
        ("workflow_dispatch", "refs/heads/main", True),
        ("push", "refs/heads/develop", False),
        ("workflow_dispatch", "refs/heads/develop", False),
        ("workflow_dispatch", "refs/heads/feature", False),
        ("pull_request", "refs/pull/1/merge", False),
        ("pull_request", "refs/heads/main", False),
        ("push", "refs/tags/main", False),
    ],
)
def test_pages_publishes_only_main(event, ref, expected):
    job = pages_job()
    # Evaluate this deliberately simple Boolean guard with the same truth table.
    guard = job["if"].replace("&&", " and ").replace("||", " or ")
    guard = guard.replace("github.event_name", repr(event)).replace("github.ref", repr(ref))
    assert eval(guard, {"__builtins__": {}}) is expected
    assert job["needs"] == "overview"
    assert "always()" not in job["if"]  # a failed overview must not publish
    assert job["permissions"] == {"contents": "read", "pages": "write", "id-token": "write"}
    assert job["environment"]["name"] == "github-pages"
    assert job["concurrency"]["cancel-in-progress"] is False


@pytest.mark.parametrize("report_count", [0, 1, 2])
def test_pages_staging_requires_one_report_and_preserves_landing(tmp_path, report_count):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.html").write_text("<html>Existing landing page</html>")
    reports = tmp_path / "ci-reports/overview"
    reports.mkdir(parents=True)
    for index in range(report_count):
        (reports / f"reducto-baseline-{index}.html").write_text("<html>Dashboard</html>")
    (reports / "private.json").write_text("not part of the public site")
    step = next(s for s in pages_job()["steps"] if s.get("name") == "Stage Pages site")
    result = subprocess.run(
        ["bash", "-e", "-c", step["run"]], cwd=tmp_path, capture_output=True, text=True
    )
    site = tmp_path / "ci-reports/pages"
    if report_count == 1:
        assert result.returncode == 0, result.stderr
        assert (site / "index.html").read_text() == (docs / "index.html").read_text()
        assert (site / "dashboard/index.html").read_text() == "<html>Dashboard</html>"
        assert {str(p.relative_to(site)) for p in site.rglob("*") if p.is_file()} == {
            "index.html",
            "dashboard/index.html",
        }
    else:
        assert result.returncode != 0
        assert "Expected exactly one" in result.stderr
        assert not site.exists()
