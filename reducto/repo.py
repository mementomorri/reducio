"""Repository file walking and language detection."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from reducto.models import FileInfo, Language
from reducto.progress import status

# Dot-directories (.git, .venv, .reducto, .pytest_cache, ...) are excluded by the
# leading-dot rule in _should_exclude_dir; only non-dot dirs need listing here.
DEFAULT_EXCLUDE_DIRS = {"venv", "node_modules", "__pycache__", "dist", "build", "target"}
BINARY_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".so",
    ".dll",
    ".dylib",
    ".exe",
    ".bin",
}
SKIP_SUFFIXES = (".min.js", ".min.css", ".lock", ".sum")


def detect_language(path: str) -> Language:
    return Language.PYTHON if Path(path).suffix.lower() == ".py" else Language.UNKNOWN


def _should_exclude_dir(name: str, path: str, patterns: list[str]) -> bool:
    if name in DEFAULT_EXCLUDE_DIRS or name.startswith("."):
        return True
    return any(name == p or p in path for p in patterns)


def _should_exclude_file(name: str) -> bool:
    if name.startswith(".") and name not in (".gitignore", ".env.example"):
        return True
    if any(name.endswith(s) for s in SKIP_SUFFIXES):
        return True
    return Path(name).suffix.lower() in BINARY_EXTS


def _should_include(path: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    ext = Path(path).suffix
    for pattern in patterns:
        if pattern.startswith("*") and ext == pattern[1:]:
            return True
        if path.endswith(pattern):
            return True
    return False


def _read_one(root: Path, path: Path) -> FileInfo:
    content = path.read_text(encoding="utf-8", errors="replace")
    rel = str(path.relative_to(root))
    digest = hashlib.sha256(content.encode()).hexdigest()
    return FileInfo(path=rel, content=content, hash=digest)


def walk(
    root: str,
    exclude_patterns: list[str] | None = None,
    include_patterns: list[str] | None = None,
) -> list[FileInfo]:
    root_path = Path(root).resolve()
    status(f"Exploring {root_path} for matching source files...")
    exclude_patterns = exclude_patterns or []
    include_patterns = include_patterns or []
    paths: list[Path] = []

    import os

    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [
            d
            for d in dirnames
            if not _should_exclude_dir(d, str(Path(dirpath) / d), exclude_patterns)
        ]
        for name in filenames:
            full = Path(dirpath) / name
            if _should_exclude_file(name):
                continue
            rel = str(full.relative_to(root_path))
            if not _should_include(rel, include_patterns):
                continue
            paths.append(full)

    status(f"Reading {len(paths)} source files...")
    files: list[FileInfo] = []
    with ThreadPoolExecutor(max_workers=32) as pool:
        futures = {pool.submit(_read_one, root_path, p): p for p in paths}
        for fut in as_completed(futures):
            files.append(fut.result())
    return files
