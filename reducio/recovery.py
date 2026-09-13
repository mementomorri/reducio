"""Durable, scoped file snapshots. No Git/index operations and no crash-atomic claim."""

from __future__ import annotations

import hashlib
import json
import stat
import uuid
from pathlib import Path

from reducio.storage import checked_file
from reducio.storage import replace_bytes as replace_bytes


def safe_target(root: Path, relative: str) -> Path:
    if {".git", ".reducio"}.intersection(Path(relative).parts):
        raise ValueError("Git and reducio metadata must not be modified")
    path = root / relative
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Symlinked targets are not supported")
    path.resolve().relative_to(root.resolve())
    if path.exists() and (not path.is_file() or path.stat().st_nlink > 1):
        raise ValueError("Only regular, non-hardlinked targets are supported")
    return path


def fingerprint(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


class FileSnapshot:
    def __init__(self, root: Path, paths: list[str]):
        self.root = root
        self.directory = root / ".reducio/recovery" / str(uuid.uuid4())
        checked_file(self.directory, "manifest.json")
        self.directory.mkdir(parents=True, mode=0o700)
        self.records: dict[str, dict] = {}
        self.written: list[str] = []
        self.created_dirs: list[Path] = []
        for number, relative in enumerate(dict.fromkeys(paths)):
            path = safe_target(root, relative)
            present = path.exists()
            content = path.read_bytes() if present else b""
            backup = f"{number}.bin"
            replace_bytes(self.directory / backup, content, 0o600)
            self.records[relative] = {
                "backup": backup,
                "exists": present,
                "mode": stat.S_IMODE(path.stat().st_mode) if present else 0o644,
                "before": hashlib.sha256(content).hexdigest() if present else None,
                "expected": hashlib.sha256(content).hexdigest() if present else None,
            }
        self._save("prepared")

    def _save(self, state: str, errors: list[str] | None = None) -> None:
        replace_bytes(
            checked_file(self.directory, "manifest.json"),
            json.dumps(
                {
                    "state": state,
                    "root": str(self.root),
                    "files": self.records,
                    "written": self.written,
                    "errors": errors or [],
                },
                indent=2,
            ).encode("utf-8"),
            0o600,
        )

    def write(self, relative: str, content: bytes) -> None:
        record = self.records[relative]
        path = safe_target(self.root, relative)
        if fingerprint(path) != record["expected"]:
            raise ValueError(f"Target changed concurrently: {relative}")
        missing = []
        parent = path.parent
        while not parent.exists():
            missing.append(parent)
            parent = parent.parent
        for parent in reversed(missing):
            parent.mkdir()
            self.created_dirs.append(parent)
        expected = hashlib.sha256(content).hexdigest()
        # Record recovery intent before the atomic replacement, then track completed writes.
        record["proposed"] = expected
        record["expected"] = expected
        self.written.append(relative)
        self._save("writing")
        replace_bytes(path, content, record["mode"])
        self._save("validating")

    def restore(self) -> list[str]:
        errors = []
        for relative in reversed(list(dict.fromkeys(self.written))):
            try:
                path = safe_target(self.root, relative)
                record = self.records[relative]
                if fingerprint(path) == record["before"]:
                    if record["exists"] and stat.S_IMODE(path.stat().st_mode) != record["mode"]:
                        raise ValueError("Target permissions changed concurrently")
                    continue
                if fingerprint(path) != record["expected"]:
                    raise ValueError("Concurrent edit detected; backup retained")
                if path.exists() and stat.S_IMODE(path.stat().st_mode) != record["mode"]:
                    raise ValueError("Target permissions changed concurrently")
                if record["exists"]:
                    content = (self.directory / record["backup"]).read_bytes()
                    if hashlib.sha256(content).hexdigest() != record["before"]:
                        raise ValueError("Backup integrity check failed")
                    replace_bytes(path, content, record["mode"])
                else:
                    path.unlink(missing_ok=True)
                if fingerprint(path) != record["before"]:
                    raise OSError("Restoration verification failed")
                if record["exists"] and stat.S_IMODE(path.stat().st_mode) != record["mode"]:
                    raise OSError("Permission restoration verification failed")
            except OSError, ValueError:
                errors.append(f"Could not safely restore {relative}; inspect retained backup")
        for directory in reversed(self.created_dirs):
            try:
                directory.rmdir()  # Never remove nonempty directories or unrelated files.
            except OSError:
                pass
        try:
            self._save("recovery_failed" if errors else "restored", errors)
        except OSError, ValueError:
            errors.append("Could not update recovery manifest")
        return errors

    def complete(self) -> None:
        for relative in self.written:
            path = safe_target(self.root, relative)
            record = self.records[relative]
            if (
                fingerprint(path) != record["expected"]
                or stat.S_IMODE(path.stat().st_mode) != record["mode"]
            ):
                raise ValueError(f"Target changed during validation: {relative}")
        self._save("applied")
