"""Session store tests."""

from datetime import datetime

from reducio.models import FileChange, RefactorPlan
from reducio.session import SessionStore


def test_save_plan_metadata_includes_session_id(tmp_path):
    store = SessionStore(storage_dir=str(tmp_path / "sessions"))
    plan = RefactorPlan(
        session_id="sess-abc",
        changes=[
            FileChange(path="a.py", original="a", modified="b", description="x"),
        ],
        description="test plan",
        created_at=datetime(2026, 5, 15, 12, 0, 0),
    )
    store.save_plan(plan, command_type="deduplicate")
    items = store.list_sessions()
    assert len(items) == 1
    assert items[0].session_id == "sess-abc"
    assert items[0].command_type == "deduplicate"
    assert items[0].change_count == 1


def test_list_sessions_legacy_metadata_uses_filename(tmp_path):
    store = SessionStore(storage_dir=str(tmp_path / "sessions"))
    path = store.storage_dir / "legacy-id.json"
    path.write_text("""{
  "metadata": {
    "version": 1,
    "created_at": "2026-05-15T12:00:00",
    "command_type": "idiomatize",
    "file_count": 1,
    "change_count": 1,
    "description": "old"
  },
  "plan": {
    "session_id": "legacy-id",
    "changes": [],
    "description": "old",
    "created_at": "2026-05-15T12:00:00"
  }
}""")
    items = store.list_sessions()
    assert len(items) == 1
    assert items[0].session_id == "legacy-id"


_LEGACY_SESSION_JSON = """{
  "metadata": {
    "version": 1,
    "created_at": "2020-01-01T00:00:00",
    "command_type": "idiomatize",
    "file_count": 1,
    "change_count": 1,
    "description": "old"
  },
  "plan": {
    "session_id": "legacy-id",
    "changes": [],
    "description": "old",
    "created_at": "2020-01-01T00:00:00"
  }
}"""


def test_get_session_info_legacy_metadata(tmp_path):
    store = SessionStore(storage_dir=str(tmp_path / "sessions"))
    (store.storage_dir / "legacy-id.json").write_text(_LEGACY_SESSION_JSON)
    info = store.get_session_info("legacy-id")
    assert info is not None
    assert info.session_id == "legacy-id"
    assert info.command_type == "idiomatize"


def test_cleanup_old_sessions_pops_cache_for_legacy_metadata(tmp_path):
    store = SessionStore(storage_dir=str(tmp_path / "sessions"))
    (store.storage_dir / "legacy-id.json").write_text(_LEGACY_SESSION_JSON)
    store.load_plan("legacy-id")
    assert store.load_plan("legacy-id") is not None
    assert store.cleanup_old_sessions(max_age_days=0) == 1
    assert store.load_plan("legacy-id") is None
    store.clear_cache()  # public compatibility no-op
