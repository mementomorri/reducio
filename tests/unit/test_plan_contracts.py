"""Persisted review, capability failure, and advisory preflight contracts."""

import ast
import builtins
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from reducio.agents.deduplicator import DeduplicatorAgent
from reducio.agents.idiomatizer import IdiomatizerAgent
from reducio.agents.pattern import PatternAgent
from reducio.models import (
    AppConfig,
    DeduplicateRequest,
    FileChange,
    FileInfo,
    IdiomatizeRequest,
    PatternRequest,
    RefactorPlan,
)
from reducio.parse import ParserError
from reducio.plan_review import advisory_path, plan_preview, terminal_text, validate_plan
from reducio.reporter import Reporter
from reducio.services import App
from reducio.session import SessionStore
from reducio.storage import StorageError
from reducio.workspace import Workspace


@pytest.mark.parametrize("fallback", [False, True])
async def test_pattern_model_failure_requires_explicit_fallback(tmp_path, fallback):
    workspace = Workspace(str(tmp_path), AppConfig(model="test/model"))
    llm = MagicMock(complete=AsyncMock(side_effect=RuntimeError("SECRET")))
    agent = PatternAgent(workspace, llm, SessionStore(str(tmp_path / "sessions")))
    plan = await agent.apply_pattern(
        PatternRequest(
            path=str(tmp_path),
            pattern="singleton",
            files=[FileInfo(path="state.py", content="global state\n")],
            allow_fallback=fallback,
        )
    )
    assert plan.complete is fallback and bool(plan.changes) is fallback
    assert "SECRET" not in plan.model_dump_json()
    assert [p.engine for p in plan.provenance] == (["model", "template"] if fallback else ["model"])


def test_parser_initialization_error_is_not_cached(monkeypatch):
    from reducio import parse

    original_import = builtins.__import__
    attempts = []

    def fail(name, *args, **kwargs):
        if name == "tree_sitter_python":
            attempts.append(name)
            raise ImportError("PRIVATE dependency details")
        return original_import(name, *args, **kwargs)

    parse._parser.cache_clear()
    monkeypatch.setattr(builtins, "__import__", fail)
    for _ in range(2):
        with pytest.raises(ParserError, match="could not initialize"):
            parse.get_symbols("def f(): pass", "a.py")
    assert len(attempts) == 2


async def test_verbose_router_does_not_log_prompts_or_provider_errors(monkeypatch, caplog):
    import httpx

    from reducio.llm import LLMClient, LLMError

    monkeypatch.setenv("REDUCIO_API_KEY", "SECRET")
    caplog.set_level("INFO")
    monkeypatch.setattr(
        httpx.AsyncClient, "post", AsyncMock(side_effect=RuntimeError("SECRET PRIVATE"))
    )
    with pytest.raises(LLMError):
        await LLMClient(AppConfig(verbose=True, llm_api="openai", model="chosen")).complete(
            "PRIVATE"
        )
    assert "SECRET" not in caplog.text and "PRIVATE" not in caplog.text


@pytest.mark.parametrize(
    "session_id",
    ["", ".", "..", "../escape", "/tmp/escape", "a/b", r"a\b", r"C:\escape", "a\n", "a\x1b"],
)
def test_session_ids_rejected_before_cache_or_filesystem(tmp_path, session_id):
    store = SessionStore(str(tmp_path / "sessions"))
    plan = RefactorPlan(session_id=session_id, changes=[], description="cached")
    for operation in (store.load_plan, store.delete_session, store.get_session_info):
        with pytest.raises(StorageError):
            operation(session_id)
    with pytest.raises(StorageError):
        store.save_plan(plan)
    with pytest.raises(StorageError):
        Reporter(output_dir=tmp_path).generate_dry_run(plan, "idiomatize", ".")


def test_session_symlink_and_metadata_mismatch(tmp_path, caplog):
    store = SessionStore(str(tmp_path / "sessions"))
    plan = RefactorPlan(session_id="safe", changes=[], description="test")
    store.save_plan(plan)
    path = tmp_path / "sessions/safe.json"
    envelope = json.loads(path.read_text())
    envelope["metadata"]["session_id"] = "different"
    path.write_text(json.dumps(envelope))
    assert store.load_plan("safe") is None
    assert store.list_sessions() == []
    assert store.cleanup_old_sessions(0) == 0
    outside = tmp_path / "outside.json"
    path.rename(outside)
    path.symlink_to(outside)
    with pytest.raises(StorageError):
        store.load_plan("safe")
    assert store.list_sessions() == []
    assert store.cleanup_old_sessions(0) == 0
    assert outside.exists()
    assert "unsafe or malformed" in caplog.text


def test_storage_root_symlink_rejected(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(StorageError):
        SessionStore(str(tmp_path / "link/sessions"))


@pytest.mark.parametrize(
    "reply", [RuntimeError("credential=SECRET prompt=PRIVATE"), "", "not valid python !"]
)
@pytest.mark.parametrize("fallback", [False, True])
async def test_model_failure_is_explicit_and_persisted(tmp_path, reply, fallback):
    ws = Workspace(str(tmp_path), AppConfig(model="test/model"))
    llm = MagicMock()
    llm.complete = AsyncMock(
        **({"side_effect": reply} if isinstance(reply, Exception) else {"return_value": reply})
    )
    store = SessionStore(str(tmp_path / ".reducio/sessions"))
    source = "def f():\n    x = None\n    return x == None\n"
    agent = IdiomatizerAgent(ws, llm, store)
    plan = await agent.idiomatize(
        IdiomatizeRequest(
            path=str(tmp_path),
            files=[FileInfo(path="f.py", content=source)],
            allow_fallback=fallback,
        )
    )
    assert plan.complete is fallback
    assert bool(plan.changes) is fallback
    assert [p.engine for p in plan.provenance] == (
        ["model", "heuristic"] if fallback else ["model"]
    )
    restored = store.load_plan(plan.session_id)
    assert restored == plan
    assert "SECRET" not in plan.model_dump_json() and "PRIVATE" not in plan.model_dump_json()
    if not fallback:
        assert not App(str(tmp_path)).apply_plan(restored, run_tests=False).success


async def test_unchanged_model_does_not_run_heuristics(tmp_path):
    content = "def f():\n    x = None\n    return x == None\n"
    llm = MagicMock(complete=AsyncMock(return_value=content))
    agent = IdiomatizerAgent(
        Workspace(str(tmp_path), AppConfig(model="test")),
        llm,
        SessionStore(str(tmp_path / "sessions")),
    )
    plan = await agent.idiomatize(
        IdiomatizeRequest(
            path=str(tmp_path), files=[FileInfo(path="f.py", content=content)], allow_fallback=True
        )
    )
    assert plan.complete and not plan.changes
    assert plan.provenance[0].outcome == "unchanged"


async def test_advisory_scope_and_dependency_filter(tmp_path):
    source = """import math
CONST = 3
def safe(x):
    return abs(x)
def dependent(x):
    return math.sqrt(x) + CONST
def defaults(x=CONST):
    return x
class C:
    def method(self):
        return self
def outer(x):
    def inner():
        return x
    return inner()
"""
    emb = MagicMock(is_using_real_embeddings=True, find_duplicates=AsyncMock(return_value=[]))
    agent = DeduplicatorAgent(
        Workspace(str(tmp_path)), emb, session_store=SessionStore(str(tmp_path / "sessions"))
    )
    plan = await agent.find_duplicates(
        DeduplicateRequest(path=str(tmp_path), files=[FileInfo(path="a.py", content=source)])
    )
    blocks = emb.find_duplicates.call_args.args[0]
    assert {b.symbol_name for b in blocks} == {"safe", "outer"}
    for block in blocks:
        ast.parse(block.content)
    assert {d.code for d in plan.diagnostics} == {"dependencies", "unsupported_scope"}
    assert plan.complete


async def test_parser_failure_is_incomplete_but_ast_analysis_works(tmp_path, monkeypatch):
    from reducio import parse

    monkeypatch.setattr(parse, "_parser", MagicMock(side_effect=ParserError("unavailable")))
    (tmp_path / "a.py").write_text("def f():\n    return 1\n")
    app = App(str(tmp_path))
    assert (await app.analyze(str(tmp_path))).complete
    emb = MagicMock(is_using_real_embeddings=True, find_duplicates=AsyncMock(return_value=[]))
    plan = await DeduplicatorAgent(app.workspace, emb, session_store=app.sessions).find_duplicates(
        DeduplicateRequest(path=str(tmp_path))
    )
    assert not plan.complete and plan.diagnostics[0].code == "parser_failed"


async def test_missing_embeddings_is_failure(tmp_path):
    emb = MagicMock(is_using_real_embeddings=False)
    plan = await DeduplicatorAgent(
        Workspace(str(tmp_path)), emb, session_store=SessionStore(str(tmp_path / "sessions"))
    ).find_duplicates(DeduplicateRequest(path=str(tmp_path)))
    assert not plan.complete and plan.diagnostics[0].code == "embeddings_unavailable"
    emb.find_duplicates.assert_not_called()


async def test_patterns_source_qualified_and_valid(tmp_path):
    content = "global state\n"
    agent = PatternAgent(
        Workspace(str(tmp_path)), session_store=SessionStore(str(tmp_path / "sessions"))
    )
    plan = await agent.apply_pattern(
        PatternRequest(
            path=str(tmp_path),
            pattern="singleton",
            files=[FileInfo(path=p, content=content) for p in ("a/12-odd.py", "b/12-odd.py")],
        )
    )
    assert plan.complete and len({c.path for c in plan.changes}) == 2
    for c in plan.changes:
        ast.parse(c.modified)
    destination = tmp_path / plan.changes[0].path
    destination.parent.mkdir()
    destination.write_text("# user content\n")
    assert not App(str(tmp_path)).apply_plan(plan, run_tests=False).success
    assert destination.read_text() == "# user content\n"


def test_conflicting_and_invalid_changes_fail_preflight(tmp_path):
    plan = RefactorPlan(
        session_id="safe",
        description="test",
        changes=[
            FileChange(path="same.py", original="", modified="x=1\n", description="first"),
            FileChange(path="same.py", original="", modified="bad syntax !", description="second"),
        ],
    )
    assert {d.code for d in validate_plan(plan, tmp_path)} == {
        "destination_conflict",
        "invalid_python",
    }
    assert not App(str(tmp_path)).apply_plan(plan, run_tests=False).success
    assert not (tmp_path / "same.py").exists()


def test_full_diff_fences_controls_and_report_lookup(tmp_path):
    plan = RefactorPlan(
        session_id="safe",
        description="review\x1b[31m",
        changes=[
            FileChange(
                path="x.py",
                original='x = "old"\n',
                modified='x = "``` <script>"',
                description="preview",
            )
        ],
    )
    reporter = Reporter(target=tmp_path)
    out = reporter.generate_dry_run(plan, "idiomatize", str(tmp_path))
    text = out.read_text()
    assert "````diff" in text and "No newline at end of file" in text
    assert '-x = "old"' in text and '+x = "``` <script>"' in text
    assert "\x1b" not in text and r"\x1b" in text
    assert reporter.load_latest("safe") == text
    assert "+++ b/x.py" in terminal_text(plan_preview(plan))
    assert advisory_path("utils", "a/x.py", "f") != advisory_path("utils", "b/x.py", "f")
