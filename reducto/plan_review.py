"""Readable persisted-plan previews and preflight checks, not an apply engine."""

from __future__ import annotations

import difflib
import hashlib
import keyword
import re
import unicodedata
from pathlib import Path

from reducto.models import FileChange, PlanDiagnostic, RefactorPlan
from reducto.storage import StorageError, validate_session_id


def terminal_text(text: str) -> str:
    return "".join(
        (
            char
            if char in "\n\t" or not unicodedata.category(char).startswith("C")
            else ascii(char)[1:-1]
        )
        for char in text
    )


def unified_preview(change: FileChange) -> str:
    lines = difflib.unified_diff(
        change.original.splitlines(keepends=True),
        change.modified.splitlines(keepends=True),
        fromfile=f"a/{change.path}" if change.original else "/dev/null",
        tofile=f"b/{change.path}" if change.modified else "/dev/null",
    )
    return "".join(
        line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines
    )


def plan_preview(plan: RefactorPlan) -> str:
    lines = [plan.description, f"Session ID: {plan.session_id}", f"Complete: {plan.complete}"]
    if not plan.provenance:
        lines.append("Planning engine: unknown (legacy or externally supplied plan)")
    for item in plan.provenance:
        lines.append(
            f"{item.file}: {item.engine} {item.outcome}"
            + (f" ({item.model})" if item.model else "")
        )
    for diagnostic in plan.diagnostics:
        lines.append(
            f"{diagnostic.severity}: {diagnostic.file}: {diagnostic.code}: {diagnostic.message}"
        )
    for change in plan.changes:
        lines.extend([f"\n{change.path}: {change.description}", unified_preview(change)])
    return "\n".join(lines)


def identifier(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]", "_", name) or "module"
    return "module_" + name if name[0].isdigit() or keyword.iskeyword(name) else name


def advisory_path(directory: str, source: str, label: str) -> str:
    digest = hashlib.sha256(source.encode()).hexdigest()[:12]
    return f"{directory}/{identifier(Path(source).stem)}_{identifier(label)}_{digest}.py"


def validate_plan(plan: RefactorPlan, root: Path | None = None) -> list[PlanDiagnostic]:
    errors = []
    try:
        validate_session_id(plan.session_id)
    except StorageError:
        errors.append(
            PlanDiagnostic(
                code="invalid_session_id", message="Invalid session ID", severity="error"
            )
        )
    seen: dict[str, FileChange] = {}
    for change in plan.changes:
        try:
            if root is not None:
                target = (root / change.path).resolve()
                target.relative_to(root.resolve())
                key = str(target)
            else:
                if Path(change.path).is_absolute() or ".." in Path(change.path).parts:
                    raise ValueError("outside target")
                target, key = Path(change.path), change.path
        except ValueError, OSError:
            errors.append(
                PlanDiagnostic(
                    code="path_escape",
                    file=change.path,
                    message="Destination escapes target",
                    severity="error",
                )
            )
            continue
        if key in seen:
            errors.append(
                PlanDiagnostic(
                    code="destination_conflict",
                    file=change.path,
                    message="Different changes target the same destination",
                    severity="error",
                )
            )
        seen[key] = change
        if (
            root is not None
            and not change.original
            and (target.exists() or (root / change.path).is_symlink())
        ):
            errors.append(
                PlanDiagnostic(
                    code="destination_exists",
                    file=change.path,
                    message="Refusing to create over existing file",
                    severity="error",
                )
            )
        if change.path.endswith(".py"):
            try:
                compile(change.modified, change.path, "exec")
            except SyntaxError, ValueError:
                errors.append(
                    PlanDiagnostic(
                        code="invalid_python",
                        file=change.path,
                        message="Proposed Python is invalid",
                        severity="error",
                    )
                )
    return errors
