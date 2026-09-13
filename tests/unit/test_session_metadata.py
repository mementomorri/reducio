"""Session metadata characterization (legacy JSON survives refactors)."""

from reducio.session import SessionStore

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


def test_list_sessions_legacy_metadata(tmp_path):
    store = SessionStore(storage_dir=str(tmp_path / "sessions"))
    store.storage_dir.mkdir(exist_ok=True)
    (store.storage_dir / "legacy-id.json").write_text(_LEGACY_SESSION_JSON)
    items = store.list_sessions()
    assert len(items) == 1
    assert items[0].session_id == "legacy-id"
    assert items[0].command_type == "idiomatize"


def test_get_session_info_legacy_metadata(tmp_path):
    store = SessionStore(storage_dir=str(tmp_path / "sessions"))
    store.storage_dir.mkdir(exist_ok=True)
    (store.storage_dir / "legacy-id.json").write_text(_LEGACY_SESSION_JSON)
    info = store.get_session_info("legacy-id")
    assert info is not None
    assert info.session_id == "legacy-id"
