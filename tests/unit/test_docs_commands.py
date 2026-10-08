"""Documented commands must match the CLI: parse every example without running it."""

from pathlib import Path

import pytest

from scripts.doc_commands import documented_commands, main, parse

ROOT = Path(__file__).resolve().parents[2]
COMMANDS = documented_commands(ROOT)


def test_documentation_has_examples():
    assert len(COMMANDS) >= 30
    assert {source for source, _ in COMMANDS} >= {"README.md", "LLM.md", "analysis.yml"}


@pytest.mark.parametrize("source,line", COMMANDS, ids=[f"{s}:{c[:50]}" for s, c in COMMANDS])
def test_documented_command_parses(source, line):
    parse(line)


@pytest.mark.parametrize(
    "line",
    ["reducio analyze . --no-such-flag", "reducio nonexistent .", "reducio analyze . --format pdf"],
)
def test_parser_rejects_drift(line):
    with pytest.raises(BaseException):
        parse(line)


def test_main_reports_drift(tmp_path, capsys):
    (tmp_path / "README.md").write_text("```bash\nreducio analyze . --bogus\n```\n")
    assert main(tmp_path) == 1
    assert "--bogus" in capsys.readouterr().out
    assert main(ROOT) == 0
