"""Utilities — complexity via workspace/parse."""

from reducio.models import ComplexityMetrics


def calculate_complexity(code: str) -> ComplexityMetrics:
    from reducio.parse import get_complexity

    return get_complexity(code)


__all__ = ["calculate_complexity"]
