"""
Session persistence for refactoring plans.

Stores plans to disk so they can be listed, applied later, and resumed across CLI invocations.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from reducio.models import RefactorPlan
from reducio.storage import StorageError, checked_file, read_text, validate_session_id, write_text

logger = logging.getLogger(__name__)


@dataclass
class SessionInfo:
    """Metadata about a stored session."""

    session_id: str
    created_at: datetime
    command_type: str
    file_count: int
    change_count: int
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "command_type": self.command_type,
            "file_count": self.file_count,
            "change_count": self.change_count,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SessionInfo:
        return cls(
            session_id=data["session_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            command_type=data["command_type"],
            file_count=data["file_count"],
            change_count=data["change_count"],
            description=data.get("description", ""),
        )


class SessionStore:
    """Persistent storage for refactoring plans."""

    def __init__(self, storage_dir: str = ".reducio/sessions"):
        self.storage_dir = Path(storage_dir)
        self._cache: dict[str, RefactorPlan] = {}
        self._ensure_storage_dir()

    def _ensure_storage_dir(self):
        """Create storage directory if it doesn't exist."""
        checked_file(self.storage_dir, "probe.json")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Session storage directory: {self.storage_dir}")

    def _get_session_path(self, session_id: str) -> Path:
        """Get the file path for a session."""
        return checked_file(self.storage_dir, f"{validate_session_id(session_id)}.json")

    @staticmethod
    def _metadata_with_session_id(metadata: dict, session_path: Path) -> dict:
        if "session_id" in metadata:
            return metadata
        return {**metadata, "session_id": session_path.stem}

    def _read_session_file(self, session_path: Path) -> dict | None:
        try:
            path = self._get_session_path(session_path.stem)
            data = json.loads(read_text(path))
            if not isinstance(data, dict):
                raise ValueError("Invalid session envelope")
            metadata = data.get("metadata", {})
            if not isinstance(metadata, dict):
                raise ValueError("Invalid metadata")
            for record in (metadata, data.get("plan", {})):
                if not isinstance(record, dict) or record.get("session_id", path.stem) != path.stem:
                    raise ValueError("Session ID does not match filename")
            if metadata:
                info = SessionInfo.from_dict(self._metadata_with_session_id(metadata, path))
                # Normalize dates for sorting/cleanup; also reject malformed metadata early.
                info.created_at.timestamp()
            return data
        except OSError, ValueError, TypeError, KeyError:
            logger.warning("Skipping unsafe or malformed session file")
            return None

    def save_plan(self, plan: RefactorPlan, command_type: str = "unknown") -> None:
        """
        Save a refactoring plan to disk.

        Args:
            plan: The RefactorPlan to save
            command_type: Type of command that generated this plan
                         (deduplicate, idiomatize, pattern)
        """
        session_path = self._get_session_path(plan.session_id)

        # Create metadata
        metadata = {
            "version": 1,
            "session_id": plan.session_id,
            "created_at": (
                plan.created_at.isoformat() if plan.created_at else datetime.now().isoformat()
            ),
            "command_type": command_type,
            "file_count": len(set(c.path for c in plan.changes)),
            "change_count": len(plan.changes),
            "description": plan.description[:200] if plan.description else "",
        }

        # Serialize plan
        data = {
            "metadata": metadata,
            "plan": plan.model_dump(mode="json"),
        }

        # Write to file
        try:
            write_text(session_path, json.dumps(data, indent=2))

            # Update cache
            self._cache[plan.session_id] = plan

            logger.info(f"Saved session {plan.session_id} ({len(plan.changes)} changes)")
        except Exception as e:
            logger.error(f"Failed to save session {plan.session_id}: {e}")
            raise

    def load_plan(self, session_id: str) -> RefactorPlan | None:
        """
        Load a refactoring plan from disk.

        Args:
            session_id: The session ID to load

        Returns:
            The RefactorPlan if found, None otherwise
        """
        session_path = self._get_session_path(session_id)
        # Validate before using caches; cached data must not bypass replaced files.
        if session_id in self._cache:
            self._cache.pop(session_id, None)

        if not session_path.exists():
            logger.warning(f"Session {session_id} not found")
            return None

        try:
            data = self._read_session_file(session_path)
            if not data:
                return None

            plan_data = data.get("plan")
            if not plan_data:
                logger.error(f"Invalid session file {session_id}: no plan data")
                return None

            plan = RefactorPlan.model_validate(plan_data)
            if plan.session_id != session_id:
                raise StorageError("Session ID does not match filename")
            self._cache[session_id] = plan

            logger.info(f"Loaded session {session_id} ({len(plan.changes)} changes)")
            return plan

        except ValueError, TypeError:
            logger.error("Failed to load malformed session")
            return None

    def list_sessions(self) -> list[SessionInfo]:
        """
        List all stored sessions.

        Returns:
            List of SessionInfo objects, sorted by created_at (newest first)
        """
        sessions = []

        for session_path in self.storage_dir.glob("*.json"):
            data = self._read_session_file(session_path)
            if not data:
                continue
            metadata = data.get("metadata", {})
            if not metadata:
                continue
            sessions.append(
                SessionInfo.from_dict(self._metadata_with_session_id(metadata, session_path))
            )

        # Sort by created_at, newest first
        sessions.sort(key=lambda s: s.created_at.timestamp(), reverse=True)
        return sessions

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session from storage.

        Args:
            session_id: The session ID to delete

        Returns:
            True if deleted, False if not found
        """
        session_path = self._get_session_path(session_id)

        if not session_path.exists():
            return False

        try:
            session_path.unlink()
            self._cache.pop(session_id, None)
            logger.info(f"Deleted session {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            return False

    def cleanup_old_sessions(self, max_age_days: int = 7) -> int:
        """
        Delete sessions older than max_age_days.

        Args:
            max_age_days: Maximum age in days (default: 7)

        Returns:
            Number of sessions deleted
        """
        if max_age_days < 0:
            raise ValueError("Session age must be nonnegative")
        cutoff = (datetime.now() - timedelta(days=max_age_days)).timestamp()
        deleted = 0

        for session_path in self.storage_dir.glob("*.json"):
            data = self._read_session_file(session_path)
            if not data:
                continue
            metadata = data.get("metadata", {})
            created_at_str = metadata.get("created_at")
            if not created_at_str:
                continue
            if datetime.fromisoformat(created_at_str).timestamp() < cutoff:
                self._get_session_path(session_path.stem).unlink()
                session_id = self._metadata_with_session_id(metadata, session_path)["session_id"]
                self._cache.pop(session_id, None)
                deleted += 1
                logger.debug(f"Deleted old session {session_id}")

        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old sessions")

        return deleted

    def get_session_info(self, session_id: str) -> SessionInfo | None:
        """
        Get metadata for a session without loading the full plan.

        Args:
            session_id: The session ID

        Returns:
            SessionInfo if found, None otherwise
        """
        session_path = self._get_session_path(session_id)

        if not session_path.exists():
            return None

        data = self._read_session_file(session_path)
        if not data:
            return None
        metadata = data.get("metadata", {})
        if not metadata:
            return None
        return SessionInfo.from_dict(self._metadata_with_session_id(metadata, session_path))

    def clear_cache(self):
        """Clear the in-memory cache."""
        self._cache.clear()
        logger.debug("Session cache cleared")
