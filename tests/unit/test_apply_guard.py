"""apply_plan refuses whole-file rewrites that drop a def/class."""

import pytest

from reducto.models import FileChange, RefactorPlan
from reducto.services import App


@pytest.mark.asyncio
async def test_apply_plan_refuses_dropping_a_def(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("def keep():\n    return 1\n\n\ndef also():\n    return 2\n")
    app = App(str(tmp_path))
    plan = RefactorPlan(
        session_id="x",
        description="drops a def",
        changes=[
            FileChange(
                path="m.py",
                original=f.read_text(),
                modified="def keep():\n    return 1\n",  # `also` gone
                description="bad rewrite",
            )
        ],
    )
    result = app.apply_plan(plan, run_tests=False)
    assert not result.success
    assert "also" in result.error
    assert f.read_text().count("def ") == 2  # untouched
