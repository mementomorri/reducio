"""Regression cases reproduced in the reliability/code-reduction review."""

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reducio.analysis import analyze_files
from reducio.cli import app as cli
from reducio.models import AppConfig, FileChange, FileInfo, RefactorPlan
from reducio.repo import included, walk
from reducio.services import App
from reducio.session import SessionStore
from reducio.storage import StorageError, write_text


@pytest.mark.parametrize(
    "source",
    [
        b"def f():\r\n    x = None\r\n    return x == None\r\n",
        b"\xef\xbb\xbfdef f():\n    x = None\n    return x == None\n",
        b'# coding: latin-1\nLABEL = "caf\xe9"\ndef f():\n    x = None\n    return x == None\n',
    ],
)
async def test_native_plan_roundtrips_original_bytes(tmp_path, source):
    path = tmp_path / "source.py"
    path.write_bytes(source)
    service = App(str(tmp_path), AppConfig())
    plan = await service.idiomatize(str(tmp_path))
    assert plan.schema_version == 2 and plan.complete and len(plan.changes) == 1
    change = plan.changes[0]
    assert change.operation == "replace"
    assert change.original.encode(change.encoding) == source
    saved = service.sessions.load_plan(plan.session_id)
    assert service.apply_plan(saved).success
    assert path.read_bytes() == source.replace(b"x == None", b"x is None")


@pytest.mark.parametrize("command", ["analyze", "check", "idiomatize", "pattern"])
def test_unreadable_and_invalid_source_are_incomplete(tmp_path, command):
    (tmp_path / "bad.py").write_bytes(b"\xff\xff")
    (tmp_path / "invalid.py").write_text("def broken(:")
    (tmp_path / "good.py").write_text("def f():\n    x = None\n    return x == None\n")
    args = (
        [command, str(tmp_path)] if command != "pattern" else [command, "strategy", str(tmp_path)]
    )
    args += ["--dry-run"] if command in ("idiomatize", "pattern") else ["--report"]
    result = CliRunner().invoke(cli, [*args, "--quiet"])
    assert result.exit_code == 1, result.output
    assert "Traceback" not in result.output
    assert list((tmp_path / ".reducio").glob("*.md"))
    assert "x == None" in (tmp_path / "good.py").read_text()


@pytest.mark.parametrize("command", ["analyze", "check"])
def test_read_only_commands_need_no_storage(tmp_path, monkeypatch, command):
    (tmp_path / "a.py").write_text("x = 1\n")

    def deny(*a, **kw):
        raise AssertionError("Read-only command attempted mkdir")

    monkeypatch.setattr(Path, "mkdir", deny)
    result = CliRunner().invoke(cli, [command, str(tmp_path), "--quiet"])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / ".reducio").exists()


def test_root_relative_exclusions_and_globs(tmp_path):
    target = tmp_path / "venv-in-parent" / "target"
    (target / "src/nested").mkdir(parents=True)
    for name in ("src/a.py", "src/nested/b.py", "src/ignored.py", "excluded.py"):
        (target / name).write_text("pass\n")
    files = walk(str(target), ["ignored.py", "excluded.py"], ["src/**/*.py"])
    assert [f.path for f in files] == ["src/a.py", "src/nested/b.py"]
    assert included("src/a.py", [], ["*.py"])
    assert not included("src/a.py", ["src/"], ["*.py"])


def test_symlinks_and_fifo_are_not_read(tmp_path):
    root = tmp_path / "target"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("PRIVATE")
    (root / "link.py").symlink_to(outside)
    (root / "linkdir").symlink_to(tmp_path, target_is_directory=True)
    os.mkfifo(root / "pipe.py")
    files = walk(str(root))
    assert len(files) == 3 and all(f.error and not f.content for f in files)
    assert not analyze_files(files, AppConfig()).complete


@pytest.mark.parametrize(
    "field,value",
    [
        ("check_fali_on", "warning"),
        ("dry_run", True),
        ("report", True),
        ("pre_approve", True),
        ("complexity_thresholds", {"lines_of_code": 0}),
        ("complexity_thresholds", {"cyclomatic_complexity": -1}),
        ("complexity_thresholds", {"typo": 10}),
    ],
)
def test_bad_configuration_rejected(field, value):
    with pytest.raises(ValueError):
        AppConfig.model_validate({field: value})


async def test_names_ignore_strings_comparisons_and_parse_all_arguments():
    service = __import__(
        "reducio.agents.quality_checker", fromlist=["QualityCheckerAgent"]
    ).QualityCheckerAgent()
    content = 'text = "zz=1"\nassert zz == 1\ndef doSomething(\n    qq: int = 1,\n    *, xy: str = "",\n): pass\nasync def BAD(): pass\n'
    report = await service.check_quality([FileInfo(path="a.py", content=content)], ".")
    assert not any(i.symbol == "zz" for i in report.issues)
    assert {i.symbol for i in report.issues if i.issue_type == "naming_convention"} == {
        "doSomething",
        "BAD",
    }
    assert {i.symbol for i in report.issues if i.issue_type == "bad_parameter_name"} == {"qq", "xy"}


async def test_patterns_ignore_comment_and_string_triggers(tmp_path):
    (tmp_path / "a.py").write_text(
        '# if if if if if\ntext = "global state; return new Handler(); notify()"\n'
    )
    service = App(str(tmp_path), AppConfig())
    for pattern in ("", "strategy", "factory", "observer", "singleton"):
        plan = await service.pattern(pattern, str(tmp_path))
        assert plan.complete and not plan.changes


def test_legacy_drift_never_writes(tmp_path):
    source = tmp_path / "a.py"
    source.write_bytes(b"x = 1\r\n")
    changes = [
        FileChange(path="a.py", original="x = 1\n", modified="x = 2\n", description="legacy")
    ]
    result = App(str(tmp_path), AppConfig()).apply_plan(
        RefactorPlan(session_id="legacy", changes=changes, description="legacy")
    )
    assert not result.success and "regenerate" in result.error
    assert source.read_bytes() == b"x = 1\r\n"


def test_atomic_write_failure_retains_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "saved.json"
    path.write_text("previous")

    def fail(*args):
        raise OSError("simulated failure")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        write_text(path, "replacement")
    assert path.read_text() == "previous"
    assert list(tmp_path.iterdir()) == [path]


def test_atomic_writes_do_not_follow_links_or_replace_directories(tmp_path):
    source = tmp_path / "source"
    source.write_text("private")
    linked = tmp_path / "hardlink"
    linked.hardlink_to(source)
    write_text(linked, "new report")
    assert source.read_text() == "private"
    assert linked.read_text() == "new report"
    symlink = tmp_path / "symlink"
    symlink.symlink_to(source)
    directory = tmp_path / "directory"
    directory.mkdir()
    for target in (symlink, directory):
        with pytest.raises(StorageError):
            write_text(target, "rejected")
    assert source.read_text() == "private"


def test_same_second_reports_keep_both_results(tmp_path):
    from reducio.reporter import Reporter

    reporter = Reporter(output_dir=tmp_path)
    first = reporter.generate_check({"total_issues": 1})
    second = reporter.generate_check({"total_issues": 2})
    assert first != second
    assert "| Total Issues | 1 |" in first.read_text()
    assert "| Total Issues | 2 |" in second.read_text()


def test_session_write_failure_is_clean_cli_error(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("x = 1\n")

    def fail(*args, **kwargs):
        raise PermissionError("private exception detail")

    monkeypatch.setattr(SessionStore, "save_plan", fail)
    result = CliRunner().invoke(cli, ["idiomatize", str(tmp_path), "--dry-run", "--quiet"])
    assert result.exit_code == 1
    assert "storage permissions" in result.output
    assert "private exception detail" not in result.output
    assert (tmp_path / "a.py").read_text() == "x = 1\n"


def test_directory_read_failure_is_reported(tmp_path, monkeypatch):
    def denied(root, *, onerror):
        onerror(PermissionError(13, "denied", str(root / "blocked")))
        return iter(())

    monkeypatch.setattr(os, "walk", denied)
    result = analyze_files(walk(str(tmp_path)), AppConfig())
    assert not result.complete and result.diagnostics[0].file == "blocked"


def test_plan_versions_and_empty_replacements(tmp_path):
    from reducio.plan_review import unified_preview

    source = tmp_path / "a.py"
    source.write_bytes(b"x = 1\n")
    service = App(str(tmp_path), AppConfig())
    change = FileChange(path="a.py", original="x = 1\n", modified="", description="clear")
    plan = RefactorPlan(session_id="v2", schema_version=2, changes=[change], description="test")
    assert not service.apply_plan(plan).success
    assert source.read_bytes() == b"x = 1\n"
    # Legacy UTF-8 plans remain usable only with a byte-exact original.
    plan.schema_version = 1
    assert service.apply_plan(plan).success
    assert source.exists() and source.read_bytes() == b""
    assert "+++ b/a.py" in unified_preview(change)
    change.original, change.modified, change.operation = "", "x = 2\n", "replace"
    plan.schema_version = 2
    assert service.apply_plan(plan).success
    assert source.read_bytes() == b"x = 2\n"


async def test_exception_import_and_match_bindings_are_checked():
    from reducio.agents.quality_checker import QualityCheckerAgent

    source = "import os as zz\ntry: pass\nexcept Exception as xy: pass\nmatch {}:\n    case {'k': xx, **qq}: pass\n"
    report = await QualityCheckerAgent().check_quality([FileInfo(path="a.py", content=source)], ".")
    assert {issue.symbol for issue in report.issues} == {"zz", "xy", "xx", "qq"}


def test_unencodable_proposal_never_writes(tmp_path):
    source = tmp_path / "a.py"
    source.write_bytes(b"x = 1\r\n")
    change = FileChange(
        path="a.py",
        original="x = 1\r\n",
        modified='x = "\u20ac"\n',
        encoding="ascii",
        operation="replace",
        description="invalid encoding",
    )
    assert (
        not App(str(tmp_path), AppConfig())
        .apply_plan(RefactorPlan(session_id="encoding", changes=[change], description="invalid"))
        .success
    )
    assert source.read_bytes() == b"x = 1\r\n"
