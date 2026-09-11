"""Validation shared by persisted sessions and Markdown report lookup."""

from __future__ import annotations

import os
import re
from pathlib import Path


class StorageError(ValueError):
    pass


def validate_session_id(session_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", session_id):
        raise StorageError("Invalid session ID: use letters, digits, dots, underscores, or hyphens")
    return session_id


def checked_file(directory: Path, name: str) -> Path:
    root = directory.absolute()
    if Path(name).name != name or "/" in name or "\\" in name:
        raise StorageError("Invalid storage filename")
    path = root / name
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise StorageError("Symlinked storage files/directories are not supported")
    if path.resolve().parent != root.resolve():
        raise StorageError("Storage path escapes its directory")
    return path


def read_text(path: Path) -> str:
    # Refuse final-component symlinks even if replaced after validation.
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        return stream.read()


def write_text(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(text)
