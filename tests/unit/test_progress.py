"""Progress must arrive during work, stay off stdout, and stop even on failure."""

import io
import subprocess
import sys
from threading import Event
from threading import enumerate as threads

import pytest
from typer.testing import CliRunner

from reducto.cli import app
from reducto.progress import _Progress, progress, status


@pytest.mark.parametrize("fail", [False, True])
def test_heartbeat_during_work_and_cleanup(monkeypatch, fail):
    received = Event()

    class Stream(io.StringIO):
        def write(self, text):
            result = super().write(text)
            if "Still working:" in text:
                received.set()
            return result

    stream = Stream()
    monkeypatch.setattr("sys.stderr", stream)
    try:
        with progress("Preparing...", interval=0.01):
            assert "Preparing..." in stream.getvalue()  # visible before work
            status("Analyzing...")
            assert received.wait(2), "No heartbeat while the operation was blocked"
            if fail:
                raise RuntimeError("analysis failed")
    except RuntimeError:
        assert fail
    assert not any(thread.name == "reducto-progress" for thread in threads())
    saved = stream.getvalue()
    status("Must not leak after context exit")
    assert stream.getvalue() == saved


def test_library_silence_and_nested_quiet(capsys):
    status("Library call")
    with progress("Outer"):
        with progress("Hidden", quiet=True):
            status("Also hidden")
        status("Restored")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "[reducto] Outer\n[reducto] Restored\n"


def test_cli_progress_precedes_initialization(monkeypatch, tmp_path):
    messages = []
    update = _Progress.update

    def record(self, message):
        update(self, message)
        messages.append(message)

    monkeypatch.setattr(_Progress, "update", record)

    def slow_initialization(*args):
        assert messages == ["Preparing analysis..."]
        raise RuntimeError("initialization failed")

    monkeypatch.setattr("reducto.cli._new_app", slow_initialization)
    result = CliRunner().invoke(app, ["analyze", str(tmp_path)])
    assert isinstance(result.exception, RuntimeError)
    assert str(result.exception) == "initialization failed"
    assert not any(thread.name == "reducto-progress" for thread in threads())


@pytest.mark.parametrize("command", ["analyze", "check"])
def test_cli_progress_preserves_stdout_and_quiet_errors(tmp_path, command):
    source = tmp_path / "sample.py"
    source.write_text("def sample():\n    return 1\n")

    def run(*options):
        return subprocess.run(
            [sys.executable, "-m", "reducto.cli", command, str(tmp_path), *options],
            capture_output=True,
            text=True,
            timeout=60,
        )

    normal = run()
    quiet = run("--quiet")
    assert normal.returncode == quiet.returncode == 0
    assert normal.stdout == quiet.stdout
    assert "Exploring" in normal.stderr
    assert "Reading 1 source files" in normal.stderr
    assert quiet.stderr == ""
    source.write_text("def broken(:\n")
    failed = run("--quiet")
    assert failed.returncode == 1
    assert failed.stderr
    assert "[reducto]" not in failed.stderr
