"""E2E smoke tests for the reducto CLI (hermetic — never mutate the tracked corpus)."""

import ast
import subprocess
import sys


def _parses(path) -> bool:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
        return True
    except SyntaxError:
        return False


def _run_cli(*args: str, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "reducto.cli", *args],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=cwd,
    )


def test_help():
    r = _run_cli("--help")
    assert r.returncode == 0
    assert "analyze" in r.stdout


def test_analyze_help_flags():
    r = _run_cli("analyze", "--help")
    assert r.returncode == 0
    assert "--verbose" in r.stdout and "-v" in r.stdout
    assert "--report" in r.stdout and "-r" in r.stdout


def test_check_help_flags():
    r = _run_cli("check", "--help")
    assert r.returncode == 0
    assert "--verbose" in r.stdout and "-v" in r.stdout
    assert "--report" in r.stdout and "-r" in r.stdout


def test_analyze_sample_repo(sample_repo):
    r = _run_cli("analyze", str(sample_repo))
    assert r.returncode == 0
    assert "Files:" in r.stdout
    assert "Symbols: 0" not in r.stdout  # parser must extract symbols
    assert "cyclomatic=" not in r.stdout


def test_check_sample_repo(sample_repo):
    r = _run_cli("check", str(sample_repo))
    assert r.returncode == 0
    assert "Issues:" in r.stdout
    assert "long_function" not in r.stdout
    assert "high_complexity" not in r.stdout


def test_analyze_verbose_lists_hotspots(sample_repo):
    r = _run_cli("analyze", str(sample_repo), "-v")
    assert r.returncode == 0
    assert "Files:" in r.stdout
    assert "cyclomatic=" in r.stdout


def test_analyze_report_writes_baseline(sample_repo):
    r = _run_cli("analyze", ".", "-r", cwd=sample_repo)
    assert r.returncode == 0
    assert "Baseline report:" in r.stdout
    assert list((sample_repo / ".reducto").glob("reducto-baseline-*.md"))


def test_check_verbose_lists_issues(sample_repo):
    r = _run_cli("check", str(sample_repo), "-v")
    assert r.returncode == 0
    assert "Issues:" in r.stdout
    assert "long_function" in r.stdout or "high_complexity" in r.stdout


def test_check_report_writes_markdown(sample_repo):
    r = _run_cli("check", ".", "-r", cwd=sample_repo)
    assert r.returncode == 0
    assert "Quality report:" in r.stdout
    reports = list((sample_repo / ".reducto").glob("reducto-check-*.md"))
    assert reports
    text = reports[0].read_text()
    assert "long_function" in text or "high_complexity" in text


def test_idiomatize_sample_repo(sample_repo):
    r = _run_cli("idiomatize", str(sample_repo), "--yes")
    assert r.returncode == 0


def test_idiomatize_never_breaks_valid_python(sample_repo):
    # ROADMAP P0 guard: the apply path used to drop snippet edits at line 1 and
    # corrupt files. No file that parsed before may fail to parse after.
    py_files = [p for p in sample_repo.rglob("*.py") if ".reducto" not in p.parts]
    valid_before = {p for p in py_files if _parses(p)}
    assert valid_before  # corpus has real Python to protect

    r = _run_cli("idiomatize", str(sample_repo), "--yes")
    assert r.returncode == 0

    regressions = [str(p) for p in valid_before if not _parses(p)]
    assert not regressions, f"idiomatize corrupted valid files: {regressions}"


def test_deduplicate_sample_repo(sample_repo):
    r = _run_cli("deduplicate", str(sample_repo / "duplicates"), "--yes")
    assert r.returncode == 0
    assert "duplicate" in r.stdout.lower()


def test_apply_unknown_session_exits_1(sample_repo):
    r = _run_cli("apply", "does-not-exist", str(sample_repo))
    assert r.returncode == 1
    assert "not found" in r.stderr.lower()


def test_sessions_show_unknown_exits_1(sample_repo):
    r = _run_cli("sessions", "show", "nope", "-C", str(sample_repo))
    assert r.returncode == 1


def test_unknown_pattern_name_exits_cleanly(sample_repo):
    r = _run_cli("pattern", "banana", str(sample_repo), "--dry-run")
    assert r.returncode == 2
    assert "unknown pattern" in r.stderr.lower()
    assert "Traceback" not in r.stderr


def test_file_path_rejected_cleanly(sample_repo):
    a_file = next(sample_repo.rglob("*.py"))
    r = _run_cli("pattern", "singleton", str(a_file), "--yes")
    assert r.returncode == 2
    assert "not a directory" in r.stderr.lower()
    assert "Traceback" not in r.stderr


def test_report_without_any_report_exits_cleanly(sample_repo):
    # session-id path: no such report -> clean exit 1, never a traceback
    r = _run_cli("report", "no-such-session")
    assert r.returncode == 1
    assert "Traceback" not in r.stderr
