"""Tests for presenter.layouts.split_half_text_images."""

from __future__ import annotations

import pytest

from presenter.layouts import split_half_text_images


def test_side_right_puts_text_left_images_right() -> None:
    slide = split_half_text_images(
        "Findings",
        ["Bullet one", "Bullet two"],
        ["artifact://plots/a", "artifact://plots/b"],
        side="right",
    )
    assert slide["layout"] == "Two Content"
    assert [b["type"] for b in slide["blocks"]] == ["text", "text", "image", "image"]
    assert slide["placeholder_roles"] == {"left": [0, 1], "right": [2, 3]}


def test_side_left_puts_images_left_text_right() -> None:
    slide = split_half_text_images(
        "Findings",
        ["Bullet one"],
        ["artifact://plots/a", "artifact://plots/b"],
        side="left",
    )
    assert [b["type"] for b in slide["blocks"]] == ["image", "image", "text"]
    assert slide["placeholder_roles"] == {"left": [0, 1], "right": [2]}


def test_invalid_side_rejected() -> None:
    with pytest.raises(ValueError, match="side"):
        split_half_text_images("Findings", ["A"], ["artifact://plots/a"], side="middle")


def test_empty_image_sources_rejected() -> None:
    with pytest.raises(ValueError, match="image_sources"):
        split_half_text_images("Findings", ["A"], [])
