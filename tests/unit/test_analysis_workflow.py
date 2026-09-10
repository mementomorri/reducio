"""The workflow's parser guard must inspect data, not incidental log lines."""

import json
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
