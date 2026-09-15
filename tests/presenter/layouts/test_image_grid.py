"""Tests for presenter.layouts.image_grid."""

from __future__ import annotations

import pytest

from presenter.layouts import image_grid


def test_custom_placement_fallback_layout() -> None:
    slide = image_grid(
        "Layout snapshots",
        ["artifact://layout/a", "artifact://layout/b", "artifact://layout/c"],
        columns=3,
    )
    assert slide["layout"] == "Blank"
    assert slide["columns"] == 3
    assert [b["source"] for b in slide["blocks"]] == [
        "artifact://layout/a",
        "artifact://layout/b",
        "artifact://layout/c",
    ]
    assert all(b["caption"] is None for b in slide["blocks"])
    assert slide["placeholder_roles"] == {"grid": [0, 1, 2]}


def test_captions_align_with_images() -> None:
    slide = image_grid(
        "Layout snapshots",
        ["artifact://layout/a", "artifact://layout/b"],
        captions=["Metal 1", "Metal 2"],
    )
    assert [b["caption"] for b in slide["blocks"]] == ["Metal 1", "Metal 2"]


def test_default_columns_is_two() -> None:
    slide = image_grid("Layout snapshots", ["artifact://layout/a"])
    assert slide["columns"] == 2


def test_mismatched_captions_length_rejected() -> None:
    with pytest.raises(ValueError, match="captions"):
        image_grid(
            "Layout snapshots",
            ["artifact://layout/a", "artifact://layout/b"],
            captions=["Only one"],
        )


def test_invalid_columns_rejected() -> None:
    with pytest.raises(ValueError, match="columns"):
        image_grid("Layout snapshots", ["artifact://layout/a"], columns=0)


def test_bool_columns_rejected() -> None:
    with pytest.raises(ValueError, match="columns"):
        image_grid("Layout snapshots", ["artifact://layout/a"], columns=True)


def test_empty_image_sources_rejected() -> None:
    with pytest.raises(ValueError, match="image_sources"):
        image_grid("Layout snapshots", [])
