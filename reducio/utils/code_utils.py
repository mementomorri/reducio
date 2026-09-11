"""Helpers for quality checker (Python only)."""

import re


def extract_python_function_name(line: str) -> str:
    m = re.match(r"(?:async\s+)?def\s+([a-zA-Z_][a-zA-Z0-9_]*)", line)
    return m.group(1) if m else ""


def find_python_block_end(lines: list[str], start: int) -> int:
    if start >= len(lines):
        return len(lines)
    indent = len(lines[start]) - len(lines[start].lstrip())
    for i in range(start + 1, len(lines)):
        if lines[i].strip() and (len(lines[i]) - len(lines[i].lstrip())) <= indent:
            return i
    return len(lines)


def extract_class_name(line: str) -> str:
    line = line.replace("class ", "").strip()
    for char in "(:[{":
        idx = line.find(char)
        if idx > 0:
            line = line[:idx]
    return line.strip()


def to_snake_case(name: str) -> str:
    return re.sub(r"([A-Z])", r"_\1", name).lower().lstrip("_")


def to_pascal_case(name: str) -> str:
    return "".join(p.capitalize() for p in name.split("_") if p)


def strip_code_fence(text: str) -> str:
    """Remove a leading ```python / ``` fence and trailing ``` from an LLM reply."""
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()
