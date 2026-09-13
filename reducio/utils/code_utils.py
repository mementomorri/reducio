"""Name suggestions and model-response fence handling."""

import re


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
