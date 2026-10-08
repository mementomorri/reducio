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


# --- deduplicate --rewrite: identical same-name copies in one package ----------------------

import subprocess  # noqa: E402
import sys  # noqa: E402

import pytest  # noqa: E402

from reducio.models import AppConfig, FileChange, RefactorPlan  # noqa: E402
from reducio.services import App  # noqa: E402

SLUG = 'def slug(text):\n    """Normalize."""\n    text = text.strip().lower()\n    return text.replace(" ", "-")\n'


def _package(tmp_path, a_extra="", b_extra="", copy=SLUG, init=""):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(init)
    (pkg / "a.py").write_text(a_extra + copy + "\n\ndef use_a(x):\n    return slug(x)\n")
    (pkg / "b.py").write_bytes(
        (b_extra + copy + "\n\ndef use_b(x):\n    return slug(x) + '!'\n")
        .replace("\n", "\r\n")
        .encode()
    )
    return pkg


def _rewrite(tmp_path):
    service = App(str(tmp_path), AppConfig())
    return service, service.deduplicate(str(tmp_path), rewrite=True)


def test_rewrite_exact_duplicates_keeps_importers_working(tmp_path):
    pkg = _package(tmp_path)
    (tmp_path / "importer.py").write_text(
        "from pkg.b import slug, use_b\nprint(slug(' A B '), use_b('x'))\n"
    )
    service, plan = _rewrite(tmp_path)
    assert plan.complete, plan.diagnostics
    assert sorted(c.path for c in plan.changes) == ["pkg/_slug_shared.py", "pkg/a.py", "pkg/b.py"]
    assert "predicted physical lines" in plan.description
    result = service.apply_plan(plan)
    assert result.success, result.error
    assert result.metrics_after.lines_of_code < result.metrics_before.lines_of_code
    # Byte-exact elsewhere: CRLF file keeps its line endings, only the def is replaced.
    b = (pkg / "b.py").read_bytes()
    assert b.startswith(b"from ._slug_shared import slug\r\n") and b"\n" not in b.replace(
        b"\r\n", b""
    )
    run = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importer, pkg.a, pkg.b; assert pkg.a.slug is pkg.b.slug; print(pkg.a.use_a(' Q '))",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.split() == ["a-b", "x!", "q"]
    # Re-running finds nothing left to rewrite: copies are now imports.
    _, again = _rewrite(tmp_path)
    assert not again.changes


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"copy": SLUG.replace("(text)", "(text, seen=[])")}, "non-constant default"),
        ({"copy": SLUG.replace("(text)", '(text: "str")')}, "string annotation"),
        (
            {
                "copy": SLUG.replace(
                    "    return", "    if not text:\n        return slug('x')\n    return"
                )
            },
            "own name",
        ),
        ({"b_extra": "from __future__ import annotations\n"}, "__future__"),
        ({"a_extra": "from os.path import *\n"}, "star import"),
        ({"b_extra": "#!/usr/bin/env python\n"}, "shebang"),
        ({"a_extra": "if __name__ == '__main__':\n    pass\n"}, "__main__"),
        ({"a_extra": "slug = None\n"}, "rebound"),
        ({"init": "from . import _slug_shared\n"}, "already uses"),
    ],
)
def test_rewrite_refusals(tmp_path, kwargs, reason):
    _package(tmp_path, **kwargs)
    _, plan = _rewrite(tmp_path)
    assert not plan.changes
    refusals = [d.message for d in plan.diagnostics if d.code == "unsafe_duplicate"]
    assert refusals and reason in refusals[0], plan.diagnostics


@pytest.mark.parametrize(
    "usage",
    ["REGISTRY = {'s': slug}\n", "slug.cache = {}\n", "import pkg.a\nhandler = pkg.a.slug\n"],
)
def test_rewrite_refuses_identity_escapes_anywhere_in_workspace(tmp_path, usage):
    _package(tmp_path)
    (tmp_path / "elsewhere.py").write_text("from pkg.a import slug\n" + usage)
    _, plan = _rewrite(tmp_path)
    assert not plan.changes
    assert any("direct call" in d.message for d in plan.diagnostics)


def test_rewrite_needs_package_and_free_shared_name(tmp_path):
    pkg = _package(tmp_path)
    (pkg / "__init__.py").unlink()
    _, plan = _rewrite(tmp_path)
    assert not plan.changes and any("not a package" in d.message for d in plan.diagnostics)
    (pkg / "__init__.py").write_text("")
    (pkg / "_slug_shared.py").write_text("")
    _, plan = _rewrite(tmp_path)
    assert not plan.changes and any("already exists" in d.message for d in plan.diagnostics)


def test_rewrite_leaves_renamed_clones_as_suggestions(tmp_path):
    _package(tmp_path)
    (tmp_path / "pkg" / "b.py").write_text(SLUG.replace("slug", "make_slug"))
    _, plan = _rewrite(tmp_path)
    assert not plan.changes
    assert any(d.code == "structural_clone" for d in plan.diagnostics)


def test_dependencies_rejects_dunders_and_global_rebinding(tmp_path):
    from reducio.agents.deduplicator import _dependencies

    assert _dependencies("def tag():\n    x = 1\n    return __name__\n", "tag", set()) == {
        "__name__"
    }
    module = "def setup():\n    global len\n    len = None\n\n" + (
        "def size(xs):\n    n = len(xs)\n    return n\n"
    )
    files = [FileInfo(path="m.py", content=module), FileInfo(path="n.py", content=module)]
    plan = DeduplicatorAgent(Workspace(str(tmp_path))).find_duplicates(
        DeduplicateRequest(path=str(tmp_path), files=files), rewrite=True
    )
    assert not plan.changes  # `size` needs the module's rebound `len`
    assert any(d.code == "dependencies" and "size" in d.message for d in plan.diagnostics)


def test_guard_accepts_only_verified_sibling_import(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "a.py").write_text("def f():\n    return 1\n")
    (pkg / "other.py").write_text("def g():\n    return 2\n")
    service = App(str(tmp_path), AppConfig())

    def attempt(modified, extra=()):
        change = FileChange(
            path="pkg/a.py",
            original="def f():\n    return 1\n",
            modified=modified,
            description="x",
            operation="replace",
        )
        return service.apply_plan(
            RefactorPlan(
                schema_version=2,
                session_id="00000000-0000-4000-8000-000000000000",
                description="t",
                changes=[*extra, change],
                complete=True,
            )
        )

    for modified in (
        "from .missing import f\n",  # sibling absent
        "from .other import f\n",  # sibling lacks f
        "from pkg.other import g as f\n",  # absolute / aliased import is not verified
    ):
        result = attempt(modified)
        assert not result.success and "would drop f" in result.error
    shared = FileChange(
        path="pkg/_f_shared.py",
        original="",
        modified="def f():\n    return 1\n",
        description="s",
        operation="create",
    )
    assert attempt("from ._f_shared import f\n", [shared]).success


LONG = (
    "def summarize(rows):\n"
    "    total = 0\n"
    "    count = 0\n"
    "    for row in rows:\n"
    "        if row is None:\n"
    "            continue\n"
    "        total += row\n"
    "        count += 1\n"
    "    average = total / count if count else 0\n"
    "    return total, count, average\n"
)


def _near(tmp_path, *sources):
    files = [FileInfo(path=f"m{i}.py", content=s) for i, s in enumerate(sources)]
    return DeduplicatorAgent(Workspace(str(tmp_path))).find_duplicates(
        DeduplicateRequest(path=str(tmp_path), files=files)
    )


def test_near_miss_groups_renamed_copy_with_one_changed_statement(tmp_path):
    variant = LONG.replace("summarize(rows)", "stats(items)").replace(
        "for row in rows", "for row in items"
    )
    variant = variant.replace("        count += 1\n", "        count += 1\n        total -= 0\n")
    plan = _near(tmp_path, LONG, variant)
    (change,) = plan.changes
    assert "near-miss" in change.description and "% similar" in change.description
    assert "1 near-miss group" in plan.description and "not rewritten" in plan.description


def test_near_miss_ignores_unrelated_functions_and_keeps_exact_groups(tmp_path):
    unrelated = "def other(a, b):\n    c = a * b\n    return {c: [a, b]}\n"
    plan = _near(tmp_path, LONG, LONG.replace("summarize", "copy"), unrelated)
    (change,) = plan.changes
    assert "near-miss" not in change.description
    assert "0 near-miss group" in plan.description


def test_near_miss_is_never_rewritten(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "a.py").write_text(LONG)
    (pkg / "b.py").write_text(LONG.replace("        count += 1\n", "        count += 2\n"))
    _, plan = _rewrite(tmp_path)
    assert not plan.changes


def test_rewrite_spans_ignore_form_feeds_and_unicode_separators(tmp_path):
    # str.splitlines would split on \x0c and  ; AST line numbers do not.
    pkg = _package(tmp_path, a_extra="X = 1\n\x0c\n# sep   here\n")
    service, plan = _rewrite(tmp_path)
    assert plan.complete, plan.diagnostics
    assert service.apply_plan(plan).success
    run = subprocess.run(
        [sys.executable, "-c", "import pkg.a, pkg.b; assert pkg.a.slug is pkg.b.slug"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    assert (pkg / "a.py").read_text().startswith("X = 1\n\x0c\n# sep   here\nfrom ._slug_shared")


def test_rewrite_refuses_aliased_identity_escape(tmp_path):
    _package(tmp_path)
    (tmp_path / "elsewhere.py").write_text(
        "from pkg.a import slug as make\nREGISTRY = {'k': make}\n"
    )
    _, plan = _rewrite(tmp_path)
    assert not plan.changes
    assert any("direct call" in d.message for d in plan.diagnostics)


def test_rewrite_scans_the_whole_git_work_tree(temp_git_repo):
    src = temp_git_repo / "src"
    src.mkdir()
    _package(src)
    (src / "registry.py").write_text("from pkg.a import slug\nREGISTRY = {'s': slug}\n")
    service = App(str(src / "pkg"), AppConfig())
    plan = service.deduplicate(str(src / "pkg"), rewrite=True)
    assert not plan.changes
    assert any("direct call" in d.message for d in plan.diagnostics)
    (src / "registry.py").write_text("def broken(:\n")
    plan = App(str(src / "pkg"), AppConfig()).deduplicate(str(src / "pkg"), rewrite=True)
    assert not plan.changes
    assert any("cannot check uses in unreadable" in d.message for d in plan.diagnostics)


def test_suggestions_keep_functions_that_need_module_names(tmp_path):
    copy = "def clean(text):\n    text = re.sub('x', '', text)\n    return text.strip()\n"
    files = [FileInfo(path=f"{m}.py", content="import re\n\n\n" + copy) for m in "mn"]
    agent = DeduplicatorAgent(Workspace(str(tmp_path)))
    plan = agent.find_duplicates(DeduplicateRequest(path=str(tmp_path), files=files))
    [change] = plan.changes
    assert change.modified.startswith("# Needs from m.py: re\n")
    assert "needs module names: re" in change.description
    strict = agent.find_duplicates(
        DeduplicateRequest(path=str(tmp_path), files=files), rewrite=True
    )
    assert not strict.changes
