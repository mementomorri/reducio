"""Deterministic, byte-preserving Python source discovery shared with Git scans."""

from __future__ import annotations

import hashlib
import io
import os
import stat
import tokenize
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

from reducio.models import FileInfo, Language
from reducio.progress import status

DEFAULT_EXCLUDE_DIRS = {"venv", "node_modules", "__pycache__", "dist", "build", "target"}


def detect_language(path: str) -> Language:
    return Language.PYTHON if Path(path).suffix.lower() == ".py" else Language.UNKNOWN


def matches(path: str, patterns: list[str]) -> bool:
    candidate = PurePosixPath(path)
    return any(
        (
            candidate.full_match(pattern.rstrip("/"))
            if "/" in pattern.rstrip("/")
            else PurePosixPath(candidate.name).full_match(pattern.rstrip("/"))
        )
        for pattern in patterns
    )


def _should_exclude_dir(name: str, path: str, patterns: list[str]) -> bool:
    return name.startswith(".") or name in DEFAULT_EXCLUDE_DIRS or matches(path, patterns)


def included(path: str, excludes: list[str], includes: list[str]) -> bool:
    candidate = PurePosixPath(path)
    return (
        detect_language(path) == Language.PYTHON
        and not candidate.name.startswith(".")
        and not matches(path, excludes)
        and (not includes or matches(path, includes))
        and not any(
            _should_exclude_dir(p.name, str(p), excludes)
            for p in candidate.parents
            if str(p) != "."
        )
    )


def source_file(path: str, data: bytes) -> FileInfo:
    encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    return FileInfo(
        path=path,
        content=data.decode(encoding),
        encoding=encoding,
        hash=hashlib.sha256(data).hexdigest(),
    )


def _read_one(root: Path, path: Path) -> FileInfo:
    relative = path.relative_to(root).as_posix()
    try:
        if any(
            p.is_symlink() for p in (path, *path.parents) if p != root and p.is_relative_to(root)
        ):
            raise ValueError("Symlinked source is not supported")
        fd = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Only regular source files are supported")
            return source_file(relative, stream.read())
    except OSError, UnicodeError, LookupError, SyntaxError, ValueError:
        return FileInfo(
            path=relative,
            content="",
            error="Cannot safely read/decode source; symlinks and nonregular files are unsupported",
        )


def walk(
    root: str, exclude_patterns: list[str] | None = None, include_patterns: list[str] | None = None
) -> list[FileInfo]:
    root_path = Path(root).resolve()
    excludes = exclude_patterns or []
    includes = ["*.py"] if include_patterns is None else include_patterns
    status(f"Exploring {root_path} for matching source files...")
    paths: list[Path] = []
    errors: list[FileInfo] = []

    def failed(error):
        errors.append(
            FileInfo(
                path=Path(error.filename).relative_to(root_path).as_posix(),
                content="",
                error="Cannot explore source directory",
            )
        )

    for directory, directories, names in os.walk(root_path, onerror=failed):
        parent = Path(directory)
        directories[:] = [
            d
            for d in sorted(directories)
            if not _should_exclude_dir(d, (parent / d).relative_to(root_path).as_posix(), excludes)
        ]
        for d in directories[:]:
            if (parent / d).is_symlink():
                errors.append(
                    FileInfo(
                        path=(parent / d).relative_to(root_path).as_posix(),
                        content="",
                        error="Symlinked source directory is unsupported",
                    )
                )
                directories.remove(d)
        paths.extend(
            parent / name
            for name in names
            if included((parent / name).relative_to(root_path).as_posix(), excludes, includes)
        )
    status(f"Reading {len(paths)} source files...")
    with ThreadPoolExecutor(max_workers=32) as pool:
        files = list(pool.map(lambda p: _read_one(root_path, p), sorted(paths)))
    return sorted(files + errors, key=lambda f: f.path)
