"""Regression cases for the formerly expected section 3 safety failures."""

from reducio.models import FileChange, RefactorPlan
from reducio.services import App


def test_runner_exception_restores_original(tmp_path, monkeypatch):
    source = tmp_path / "a.py"
    source.write_text("x = 1\n")
    app = App(str(tmp_path))

    def fail(*args, **kwargs):
        raise OSError("runner unavailable")

    monkeypatch.setattr(app.workspace._runner, "run_tests", fail)
    plan = RefactorPlan(
        session_id="runner",
        description="update",
        changes=[
            FileChange(path="a.py", original="x = 1\n", modified="x = 2\n", description="update")
        ],
    )
    try:
        result = app.apply_plan(plan, run_tests=True)
    except OSError:
        result = None
    assert source.read_text() == "x = 1\n"
    assert result is not None and not result.success
