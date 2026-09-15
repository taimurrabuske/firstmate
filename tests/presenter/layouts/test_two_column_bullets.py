"""Tests for presenter.layouts.two_column_bullets."""

from __future__ import annotations

import pytest

from presenter.layouts import two_column_bullets


def test_plain_two_content_without_headings() -> None:
    slide = two_column_bullets("Comparison", ["Left A"], ["Right A", "Right B"])
    assert slide["layout"] == "Two Content"
    assert [b["text"] for b in slide["blocks"]] == ["Left A", "Right A", "Right B"]
    assert slide["placeholder_roles"] == {"left": [0], "right": [1, 2]}


def test_comparison_layout_with_headings() -> None:
    slide = two_column_bullets(
        "Comparison",
        ["Left A"],
        ["Right A"],
        left_heading="Before",
        right_heading="After",
    )
    assert slide["layout"] == "Comparison"
    blocks = slide["blocks"]
    assert blocks[0] == {"type": "text", "style": "heading2", "text": "Before"}
    assert blocks[1] == {"type": "text", "style": "body", "text": "Left A"}
    assert blocks[2] == {"type": "text", "style": "heading2", "text": "After"}
    assert blocks[3] == {"type": "text", "style": "body", "text": "Right A"}
    assert slide["placeholder_roles"] == {"left": [0, 1], "right": [2, 3]}


def test_single_heading_still_selects_comparison() -> None:
    slide = two_column_bullets(
        "Comparison", ["Left A"], ["Right A"], left_heading="Before"
    )
    assert slide["layout"] == "Comparison"
    assert slide["placeholder_roles"] == {"left": [0, 1], "right": [2]}


def test_empty_column_rejected() -> None:
    with pytest.raises(ValueError, match="right_bullets"):
        two_column_bullets("Comparison", ["Left A"], [])
