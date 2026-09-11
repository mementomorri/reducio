"""Unified diff parsing and application."""

from __future__ import annotations

import re

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class DiffError(Exception):
    pass


def apply_unified_diff(original: str, diff: str) -> str:
    lines = original.split("\n")
    hunks = _parse_hunks(diff.split("\n"))
    if not hunks and diff.strip():
        raise DiffError("No valid hunks found in diff")
    for hunk in reversed(hunks):
        lines = _apply_hunk(lines, hunk)
    return "\n".join(lines)


def _parse_hunks(diff_lines: list[str]) -> list[dict]:
    hunks: list[dict] = []
    current: dict | None = None
    for line in diff_lines:
        if line.startswith("@@ "):
            if current:
                hunks.append(current)
            m = _HUNK.match(line)
            if not m:
                continue
            current = {"old_start": int(m.group(1)), "changes": []}
        elif current and line and line[0] in "+- ":
            current["changes"].append((line[0], line[1:]))
    if current:
        hunks.append(current)
    return hunks


def _apply_hunk(lines: list[str], hunk: dict) -> list[str]:
    result: list[str] = []
    idx = 0
    while idx < hunk["old_start"] - 1 and idx < len(lines):
        result.append(lines[idx])
        idx += 1
    for kind, content in hunk["changes"]:
        if kind == " ":
            if idx >= len(lines):
                raise DiffError(f"context past end of file at line {idx + 1}: expected {content!r}")
            if lines[idx] != content:
                raise DiffError(
                    f"context mismatch at line {idx + 1}: "
                    f"expected {content!r}, found {lines[idx]!r}"
                )
            result.append(lines[idx])
            idx += 1
        elif kind == "-":
            if idx >= len(lines):
                raise DiffError(
                    f"removed line past end of file at line {idx + 1}: expected {content!r}"
                )
            if lines[idx] != content:
                raise DiffError(
                    f"removed-line mismatch at line {idx + 1}: "
                    f"expected {content!r}, found {lines[idx]!r}"
                )
            idx += 1
        elif kind == "+":
            result.append(content)
    while idx < len(lines):
        result.append(lines[idx])
        idx += 1
    return result
