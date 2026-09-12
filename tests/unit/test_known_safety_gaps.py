"""Regression cases for the formerly expected section 3 safety failures."""

import pytest

from reducio.agents.idiomatizer import IdiomatizerAgent
from reducio.models import FileChange, FileInfo, IdiomatizeRequest, RefactorPlan
from reducio.services import App
from reducio.session import SessionStore
from reducio.workspace import Workspace


@pytest.mark.parametrize(
    "source",
    [
        'def f():\n    return "x == None"\n',
        "def f():\n    out = [99]\n    for x in range(2):\n        out.append(x)\n    return out\n",
        "def f():\n    d = {}\n    for x in range(3):\n        d[x] = len(d)\n    return d\n",
    ],
)
async def test_rewrite_preserves_output(tmp_path, source):
    agent = IdiomatizerAgent(
        Workspace(str(tmp_path)), session_store=SessionStore(str(tmp_path / "sessions"))
    )
    plan = await agent.idiomatize(
        IdiomatizeRequest(path=str(tmp_path), files=[FileInfo(path="a.py", content=source)])
    )
    before, after = {}, {}
    exec(source, before)
    exec(plan.changes[0].modified if plan.changes else source, after)
    assert before["f"]() == after["f"]()


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
