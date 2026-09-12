"""Explicit target-scoped tests; never implicitly use the tool's interpreter."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from reducio.models import AppConfig


@dataclass
class TestResult:
    success: bool
    output: str
    command: str
    exit_code: int = 0
    status: str = ""
    count: int | None = None

    def __post_init__(self):
        if not self.status:
            self.status = "passed" if self.success else "failed"


class ProjectRunner:
    def __init__(self, path: str, cfg: AppConfig | None = None):
        self.path = Path(path).resolve()
        self.cfg = cfg or AppConfig()

    def _executable(self, value: str) -> str:
        candidate = Path(value)
        if candidate.is_absolute() or "/" in value or "\\" in value:
            candidate = self.path / candidate
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        elif resolved := shutil.which(value):
            return resolved
        raise ValueError("Test executable unavailable; configure test_command or test_python")

    def command(self) -> list[str]:
        if self.cfg.test_command:
            return [self._executable(self.cfg.test_command[0]), *self.cfg.test_command[1:]]
        default = ".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python"
        python = self._executable(self.cfg.test_python or default)
        if self.cfg.test_runner == "unittest":
            code = (
                "import unittest,sys; "
                "suite=unittest.defaultTestLoader.discover('.'); "
                "result=unittest.TextTestRunner(verbosity=2).run(suite); "
                "print('REDUCIO_TEST_COUNT='+str(result.testsRun)); "
                "sys.exit(5 if result.testsRun == 0 else (0 if result.wasSuccessful() else 1))"
            )
            return [python, "-c", code]
        return [python, "-m", "pytest", "-x", "-q"]

    def run_tests(self) -> TestResult:
        command: list[str] = []
        try:
            command = self.command()
            process = subprocess.run(
                command,
                cwd=self.path,
                capture_output=True,
                text=True,
                timeout=self.cfg.test_timeout_seconds,
                shell=False,
            )
            output = process.stdout + ("\n" + process.stderr if process.stderr else "")
            missing = not self.cfg.test_command and process.returncode == 5
            unavailable = not self.cfg.test_command and (
                "No module named pytest" in process.stderr
                or (self.cfg.test_runner == "pytest" and process.returncode in (2, 3, 4))
            )
            match = re.search(r"REDUCIO_TEST_COUNT=(\d+)", process.stdout)
            status = (
                "error"
                if missing or unavailable
                else ("passed" if process.returncode == 0 else "failed")
            )
            return TestResult(
                status == "passed",
                ("No tests collected.\n" if missing else "") + output.strip(),
                shlex.join(command),
                process.returncode,
                status,
                int(match[1]) if match else (0 if missing else None),
            )
        except subprocess.TimeoutExpired:
            return TestResult(False, "Requested tests timed out", shlex.join(command), -1, "error")
        except OSError, ValueError:
            return TestResult(
                False,
                "Requested tests could not start; configure the target test command/interpreter",
                shlex.join(command),
                -1,
                "error",
            )
