"""Regression tests for the seam mismatches found while wiring the four
presenter lanes (core, templates, render_docx, blocks/artifacts) together.

Each test reproduces one concrete break that surfaced only when a real
consumer crossed the seam, not from reading either side in isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from presenter.blocks.equation import build_equation
from presenter.blocks.tables import PVTCorner, SpecItem, build_pvt_table, build_spec_table
from presenter.core import DocumentBuilder
from presenter.core.blocks import EquationBlock, TableBlock, validate_block
from presenter.core.errors import BlockValidationError
from presenter.render_docx import render_document


def test_build_equation_image_field_validates(tmp_path: Path) -> None:
    """presenter.blocks.equation.build_equation() adds an 'image' key that
    presenter.core.blocks used to reject as unexpected for an equation
    block, so a builder-produced equation could never be added to a
    DocumentBuilder. It must now validate and round-trip.
    """
    block = build_equation("x^2", output_path=tmp_path / "eq.png")
    assert block["image"] is not None

    normalized = validate_block(block)
    assert normalized["image"] == block["image"]

    # The real failure mode: adding it to a document.
    spec = DocumentBuilder("T").slide("S").add(block).build()
    assert spec.slides[0].blocks[0]["image"] == block["image"]

    typed = EquationBlock.from_dict(block)
    assert typed.image == block["image"]
    assert typed.to_dict()["image"] == block["image"]


def test_build_equation_without_image_still_validates() -> None:
    block = build_equation("y", render_image=False)
    assert block["image"] is None
    validate_block(block)


def test_equation_block_still_rejects_unknown_keys() -> None:
    """The contract widening must not turn into an open door."""
    with pytest.raises(BlockValidationError, match="unexpected field"):
        validate_block({"type": "equation", "latex": "x", "bogus": "nope"})


def test_build_spec_table_alignments_field_validates() -> None:
    """build_spec_table() right/center-aligns numeric and unit columns,
    which makes build_table() attach an 'alignments' key that
    presenter.core.blocks used to reject as unexpected for a table block.
    """
    block = build_spec_table(
        [SpecItem("Vout", symbol="V", min_val=3.2, typ_val=3.3, max_val=3.4, unit="V")],
    )
    assert block["alignments"] is not None

    # The real failure mode: adding it to a document.
    spec = DocumentBuilder("T").slide("S").add(block).build()
    assert spec.slides[0].blocks[0]["alignments"] == block["alignments"]

    typed = TableBlock.from_dict(block)
    assert typed.alignments == block["alignments"]
    assert typed.to_dict()["alignments"] == block["alignments"]


def test_build_pvt_table_alignments_field_validates() -> None:
    block = build_pvt_table(
        [PVTCorner(name="TT", process="typical", voltage=1.8, temperature=25)],
    )
    assert block["alignments"] is not None
    DocumentBuilder("T").slide("S").add(block).build()


def test_table_block_alignments_length_must_match_headers() -> None:
    with pytest.raises(BlockValidationError, match="alignments"):
        validate_block(
            {"type": "table", "headers": ["A", "B"], "rows": [], "alignments": ["left"]}
        )


def test_table_block_alignments_value_must_be_known() -> None:
    with pytest.raises(BlockValidationError, match="alignments"):
        validate_block(
            {"type": "table", "headers": ["A"], "rows": [], "alignments": ["diagonal"]}
        )


def test_render_document_flattens_slides_into_heading_plus_blocks() -> None:
    """core.render.render() calls its registered engine with the full
    document dict (title/slides/...), but presenter.render_docx.render()
    takes a flat block list; render_document is the adapter that bridges
    them. A titled slide becomes a heading1 block ahead of its own blocks,
    and no page break is inserted automatically.
    """
    document = {
        "version": 1,
        "title": "T",
        "subtitle": None,
        "author": None,
        "metadata": {},
        "slides": [
            {"title": "First", "layout": None, "notes": None, "blocks": [
                {"type": "text", "style": "body", "text": "a"},
            ]},
            {"title": None, "layout": None, "notes": None, "blocks": [
                {"type": "pagebreak"},
                {"type": "text", "style": "body", "text": "b"},
            ]},
        ],
    }
    from presenter.render_docx import _flatten_document

    flat = _flatten_document(document)
    assert flat == [
        {"type": "text", "style": "heading1", "text": "First"},
        {"type": "text", "style": "body", "text": "a"},
        {"type": "pagebreak"},
        {"type": "text", "style": "body", "text": "b"},
    ]


def test_render_document_returns_path_not_summary_dict(tmp_path: Path) -> None:
    """render_docx.engine.render() returns a summary dict, but the Engine
    contract core.render.render() dispatches through requires a Path (or
    None). Calling the raw engine.render() through that dispatch would
    have raised inside Path(<dict>).
    """
    document = {
        "version": 1, "title": "T", "subtitle": None, "author": None, "metadata": {},
        "slides": [{"title": None, "layout": None, "notes": None, "blocks": [
            {"type": "text", "style": "body", "text": "hi"},
        ]}],
    }
    output_path = tmp_path / "out.docx"
    written = render_document(document, {}, output_path)
    assert written == output_path
    assert output_path.is_file()
