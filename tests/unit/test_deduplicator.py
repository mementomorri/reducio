"""DeduplicatorAgent: structural clones become suggest-only utility modules."""

from reducio.agents.deduplicator import DeduplicatorAgent, _fingerprint
from reducio.models import DeduplicateRequest, FileInfo
from reducio.plan_review import advisory_path
from reducio.workspace import Workspace

A = 'def validate_email(e):\n    """Doc."""\n    if not e:\n        raise ValueError("empty")\n    return "@" in e\n'
B = "def check_mail(addr):\n    if not addr:\n        raise Exception('missing')\n    return '#' in addr\n"


def test_renamed_clone_is_one_suggestion(tmp_path):
    plan = DeduplicatorAgent(Workspace(str(tmp_path))).find_duplicates(
        DeduplicateRequest(
            path=str(tmp_path),
            files=[FileInfo(path="a.py", content=A), FileInfo(path="b.py", content=B)],
        )
    )
    assert plan.complete and len(plan.changes) == 1
    change = plan.changes[0]
    assert change.path == advisory_path("utils", "a.py", "validate_email_1_dedup")
    assert change.original == "" and change.modified == A.rstrip("\n")
    # Honest labeling — it suggests, it does not rewrite call sites.
    assert "suggestion only" in change.description
    assert "not rewritten" in plan.description


def test_fingerprint_ignores_trivial_and_keeps_structure():
    assert _fingerprint("def f(x):\n    return x\n") is None  # one statement
    assert _fingerprint(A) != _fingerprint(A.replace('"@" in e', "e.upper()"))
