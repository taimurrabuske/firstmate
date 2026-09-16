"""Cross-cutting checks that layouts output composes with presenter.core.

presenter.layouts itself never imports presenter.core (it mirrors the other
decoupled lanes), but the blocks it hands back must still be indistinguishable
from what presenter.core.blocks would produce, and each complete helper dict
must round-trip through SlideSpec without stripping layout information.
"""

from __future__ import annotations

import pytest

from presenter.core.blocks import validate_block
from presenter.core.spec import SlideSpec
from presenter.layouts import (
    bullets_and_table,
    image_grid,
    split_half_text_images,
    title_bullets,
    title_single_image,
    two_column_bullets,
)

_SLIDES = [
    title_bullets("Overview", ["A", "B"]),
    title_single_image("Schematic", "artifact://schematics/top", caption="Top level"),
    split_half_text_images("Findings", ["A"], ["artifact://plots/a"]),
    two_column_bullets("Comparison", ["A"], ["B"], left_heading="Before"),
    bullets_and_table(
        "Electrical characteristics", ["A"], ["Parameter", "Min"], [["Vout", 3.3]]
    ),
    image_grid("Layout snapshots", ["artifact://layout/a", "artifact://layout/b"]),
]


@pytest.mark.parametrize("slide", _SLIDES)
def test_every_block_validates_against_core_contract(slide: dict) -> None:
    for block in slide["blocks"]:
        # Raises BlockValidationError on any mismatch with the shared contract;
        # the normalized form must round-trip unchanged.
        assert validate_block(block) == block


@pytest.mark.parametrize("slide", _SLIDES)
def test_complete_helper_is_a_lossless_slide_spec(slide: dict) -> None:
    spec = SlideSpec.from_dict(slide)
    assert spec.to_dict() == slide
    assert SlideSpec.from_dict(spec.to_dict()).to_dict() == slide


@pytest.mark.parametrize("slide", _SLIDES)
def test_placeholder_role_indices_cover_blocks_without_overlap(slide: dict) -> None:
    covered: list[int] = []
    for indices in slide["placeholder_roles"].values():
        covered.extend(indices)
    assert sorted(covered) == list(range(len(slide["blocks"])))
