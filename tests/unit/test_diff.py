"""Unit tests for diff application."""

import pytest

from reducio.diff import DiffError, apply_unified_diff


def test_apply_simple_hunk():
    original = "line1\nline2\nline3\n"
    diff = """@@ -2,1 +2,1 @@
-line2
+LINE2
"""
    result = apply_unified_diff(original, diff)
    assert "LINE2" in result
    assert "line2" not in result


def test_context_mismatch_raises():
    # The diff claims line 2 is "line2" but the file has "DIFFERENT" there.
    original = "line1\nDIFFERENT\nline3\n"
    diff = "@@ -2,1 +2,1 @@\n-line2\n+LINE2\n"
    with pytest.raises(DiffError):
        apply_unified_diff(original, diff)


def test_drift_past_end_of_file_raises():
    # On-disk content is shorter than the diff expects (truncation drift): the hunk's
    # removed window runs past EOF and must raise rather than silently apply.
    original = "a\nb"
    diff = "@@ -1,3 +1,2 @@\n a\n-b\n-c\n"
    with pytest.raises(DiffError):
        apply_unified_diff(original, diff)
