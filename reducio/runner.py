"""Project test runner (Python projects only)."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TestResult:
    success: bool
    output: str
    command: str
    exit_code: int = 0


class ProjectRunner:
    def __init__(self, path: str):
        self.path = Path(path).resolve()

    def _exists(self, name: str) -> bool:
        return (self.path / name).exists()

    def _is_python_project(self) -> bool:
        return (
            self._exists("pyproject.toml")
            or self._exists("setup.py")
            or self._exists("requirements.txt")
            or any(self.path.glob("**/test_*.py"))
            or self._exists("pytest.ini")
        )

    def _run(self, cmd: list[str]) -> TestResult:
        proc = subprocess.run(cmd, cwd=self.path, capture_output=True, text=True, timeout=300)
        out = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
        return TestResult(
            success=proc.returncode == 0,
            output=out.strip(),
            command=" ".join(cmd),
            exit_code=proc.returncode,
        )

    def run_tests(self) -> TestResult:
        if not self._is_python_project():
            return TestResult(success=True, output="No Python test command detected", command="")
        cmd = (
            ["python", "-m", "pytest", "-x", "-q"]
            if self._exists("pytest.ini") or self._exists("pyproject.toml")
            else ["python", "-m", "unittest", "discover", "-v"]
        )
        return self._run(cmd)
