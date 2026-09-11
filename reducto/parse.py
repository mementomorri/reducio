"""Tree-sitter symbol extraction and complexity metrics (Python only)."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tree_sitter import Parser

from reducto.metrics import get_complexity as get_complexity
from reducto.models import Language, Symbol


class ParserError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _parser() -> Parser:
    try:
        import tree_sitter_python as tspython
        from tree_sitter import Language as TSLanguage
        from tree_sitter import Parser

        language = TSLanguage(tspython.language())
        return Parser(language)
    except Exception:
        raise ParserError(
            "Python symbol parser could not initialize; check tree-sitter dependencies"
        ) from None


def get_symbols(content: str, path: str, language: Language = Language.PYTHON) -> list[Symbol]:
    if language != Language.PYTHON:
        return []
    parser = _parser()
    try:
        tree = parser.parse(content.encode())
    except Exception:
        raise ParserError("Python symbol parser failed") from None
    if tree.root_node.has_error:
        raise ParserError("Source contains invalid Python syntax")
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
