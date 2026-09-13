"""Tests for the code helpers still used by agents."""

import pytest

from reducio.utils.code_utils import strip_code_fence, to_pascal_case, to_snake_case


def test_name_suggestions():
    assert to_snake_case("someName") == "some_name"
    assert to_pascal_case("some_name") == "SomeName"


@pytest.mark.parametrize("text", ["pass", "```python\npass\n```", "```\npass\n```"])
def test_strip_code_fence(text):
    assert strip_code_fence(text) == "pass"
