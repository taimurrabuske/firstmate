"""Tests for presenter.layouts.title_single_image."""

from __future__ import annotations

import pytest

from presenter.layouts import title_single_image


def test_native_layout_and_picture_role() -> None:
    slide = title_single_image(
        "Top-level schematic",
        "artifact://schematics/ldo-top",
        width_in=5.0,
        caption="Top-level schematic",
    )
    assert slide["layout"] == "Picture with Caption"
    assert slide["blocks"] == [
        {
            "type": "image",
            "source": "artifact://schematics/ldo-top",
            "width_in": 5.0,
            "caption": "Top-level schematic",
        }
    ]
    assert slide["placeholder_roles"] == {"picture": [0]}


def test_defaults_omit_width_and_caption() -> None:
    slide = title_single_image("Schematic", "artifact://schematics/ldo-top")
    block = slide["blocks"][0]
    assert block["width_in"] is None
    assert block["caption"] is None


def test_empty_image_source_rejected() -> None:
    with pytest.raises(ValueError, match="image_source"):
        title_single_image("Schematic", "")
