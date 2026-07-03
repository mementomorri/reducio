"""Tree-sitter symbol extraction and complexity metrics (Python only)."""

from __future__ import annotations

import re
from functools import lru_cache

import tree_sitter_python as tspython
from tree_sitter import Language as TSLanguage
from tree_sitter import Parser

from reducto.models import ComplexityMetrics, Language, Symbol


@lru_cache(maxsize=1)
def _parser() -> Parser | None:
    try:
        language = TSLanguage(tspython.language())
        return Parser(language)
    except Exception:
        return None


def get_symbols(content: str, path: str, language: Language = Language.PYTHON) -> list[Symbol]:
    if language != Language.PYTHON:
        return []
    parser = _parser()
    if not parser:
        return []
    tree = parser.parse(content.encode())
    lines = content.split("\n")
    return _walk_python(tree.root_node, content.encode(), path, lines)


def _walk_python(
    node, source: bytes, path: str, lines: list[str], cls: str = "", indent: int = -1
) -> list[Symbol]:
    out: list[Symbol] = []
    for i in range(node.child_count):
        child = node.child(i)
        if child is None:
            continue
        kind = child.type
        if kind == "class_definition":
            name_node = child.child_by_field_name("name")
            if name_node:
                name = name_node.text.decode()
                start = child.start_point[0] + 1
                end = _python_block_end(lines, start - 1)
                out.append(
                    Symbol(name=name, type="class", file=path, start_line=start, end_line=end)
                )
                out.extend(_walk_python(child, source, path, lines, name, child.start_point[1]))
                continue
        if kind in ("function_definition", "async_function_definition"):
            name_node = child.child_by_field_name("name")
            if name_node:
                name = name_node.text.decode()
                stype = "method" if cls and child.start_point[1] > indent else "function"
                out.append(
                    Symbol(
                        name=name,
                        type=stype,
                        file=path,
                        start_line=child.start_point[0] + 1,
                        end_line=child.end_point[0] + 1,
                    )
                )
        out.extend(_walk_python(child, source, path, lines, cls, indent))
    return out


def _python_block_end(lines: list[str], start: int) -> int:
    if start >= len(lines):
        return len(lines)
    base = len(lines[start]) - len(lines[start].lstrip())
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line.strip() and (len(line) - len(line.lstrip())) <= base:
            return i
    return len(lines)


_NESTERS = ("if ", "elif ", "for ", "while ", "with ", "except")
# ponytail: word-boundary match so "for" isn't counted as "or", "editor" isn't "or",
# "elif" isn't "if". Still counts keywords inside string literals — acceptable heuristic.
_DECISION = re.compile(r"\b(?:if|elif|for|while|and|or)\b")


def get_complexity(content: str) -> ComplexityMetrics:
    """Cyclomatic (McCabe, base 1) and cognitive (nesting-weighted) complexity."""
    metrics = ComplexityMetrics(lines_of_code=max(1, content.count("\n") + 1))
    metrics.cyclomatic_complexity = 1
    base_indent: int | None = None
    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        metrics.cyclomatic_complexity += len(_DECISION.findall(stripped))
        if base_indent is None:
            base_indent = len(line) - len(line.lstrip())
        depth = max(0, (len(line) - len(line.lstrip()) - base_indent) // 4 - 1)
        if stripped.startswith(_NESTERS) or stripped.startswith("else:"):
            metrics.cognitive_complexity += 1 + depth
        metrics.cognitive_complexity += stripped.count(" and ") + stripped.count(" or ")
    return metrics
