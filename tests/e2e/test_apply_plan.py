"""E2E apply plan with git checkpoint."""

import subprocess
import sys

import pytest

from reducio.models import FileChange, RefactorPlan
from reducio.services import App


@pytest.mark.asyncio
async def test_apply_plan_no_tests(temp_git_repo):
    app = App(str(temp_git_repo))
    plan = RefactorPlan(
        session_id="e2e-1",
        changes=[
            FileChange(
                path="main.py",
                original="x = 1\n",
                modified="x = 2\n",
                description="bump",
            )
        ],
        description="e2e",
    )
    result = app.apply_plan(plan, run_tests=False)
    assert result.success
    assert (temp_git_repo / "main.py").read_text() == "x = 2\n"


def test_cli_check_smoke():
    r = subprocess.run(
        [sys.executable, "-m", "reducio.cli", "check", "test-python-code/python"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 1  # fixture corpus includes invalid Python
    assert "Quality check incomplete" in r.stderr
