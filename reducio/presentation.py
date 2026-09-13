"""Escaping and tables shared by terminal, Markdown and offline HTML views."""

import unicodedata
from html import escape
from typing import Any


def terminal_text(text: str) -> str:
    return "".join(
        (
            char
            if char in "\n\t" or not unicodedata.category(char).startswith("C")
            else ascii(char)[1:-1]
        )
        for char in text
    )


def markdown_cell(value: object) -> str:
    return (
        escape(terminal_text(str(value)))
        .replace("|", "&#124;")
        .replace("\n", " ")
        .replace("`", "&#96;")
        .replace("[", "&#91;")
        .replace("]", "&#93;")
    )


def table(headers: list[str], rows: list[list[Any]], html: bool = False) -> str:
    if html:
        header = "".join(f'<th scope="col">{escape(h)}</th>' for h in headers)
        body = "".join(
            "<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>" for row in rows
        )
        return f'<div class="table-scroll"><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>'

    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(markdown_cell(c) for c in row) + " |" for row in rows)
    return "\n".join(lines) + "\n"
