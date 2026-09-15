"""Tests for table-block rendering in the pptx engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from presenter.render_pptx import render


def _table_shapes(slide: Any) -> list[Any]:
    return [shape for shape in slide.shapes if shape.shape_type == MSO_SHAPE_TYPE.TABLE]


def _render_table(block: dict, tmp_path: Path) -> Any:
    output = tmp_path / "deck.pptx"
    render([block], None, output)
    return Presentation(str(output)).slides[0]


def test_table_grid_renders_headers_and_rows(tmp_path: Path) -> None:
    slide = _render_table(
        {
            "type": "table",
            "headers": ["Parameter", "Min", "Typ", "Unit"],
            "rows": [
                ["Output voltage", 3.234, 3.3, "V"],
                ["Dropout", None, 150, "mV"],
            ],
            "style": "grid",
        },
        tmp_path,
    )
    (table,) = [shape.table for shape in _table_shapes(slide)]
    assert (len(table.rows), len(table.columns)) == (3, 4)
    assert table.cell(0, 0).text == "Parameter"
    assert table.cell(0, 3).text == "Unit"
    assert table.cell(1, 1).text == "3.234"
    assert table.cell(2, 1).text == ""  # null values render as empty cells
    assert table.cell(2, 2).text == "150"
    header_run = table.cell(0, 0).text_frame.paragraphs[0].runs[0]
    assert header_run.font.bold is True
    data_run = table.cell(1, 0).text_frame.paragraphs[0].runs[0]
    assert data_run.font.bold is not True


def test_table_grid_style_sets_bold_first_row_without_banding(tmp_path: Path) -> None:
    slide = _render_table(
        {"type": "table", "headers": ["A"], "rows": [["x"]], "style": "grid"},
        tmp_path,
    )
    (table,) = [shape.table for shape in _table_shapes(slide)]
    assert table.first_row is True
    assert table.horz_banding is False


def test_table_striped_style_sets_banding(tmp_path: Path) -> None:
    slide = _render_table(
        {"type": "table", "headers": ["A"], "rows": [["x"]], "style": "striped"},
        tmp_path,
    )
    (table,) = [shape.table for shape in _table_shapes(slide)]
    assert table.first_row is True
    assert table.horz_banding is True


def test_table_plain_style_clears_first_row_and_banding(tmp_path: Path) -> None:
    slide = _render_table(
        {"type": "table", "headers": ["A"], "rows": [["x"]], "style": "plain"},
        tmp_path,
    )
    (table,) = [shape.table for shape in _table_shapes(slide)]
    assert table.first_row is False
    assert table.horz_banding is False


def test_table_caption_sits_above_the_table(tmp_path: Path) -> None:
    slide = _render_table(
        {
            "type": "table",
            "caption": "Over PVT unless noted",
            "headers": ["A", "B"],
            "rows": [["x", "y"]],
        },
        tmp_path,
    )
    (graphic_frame,) = _table_shapes(slide)
    captions = [
        shape
        for shape in slide.shapes
        if shape.has_text_frame and shape.text_frame.text == "Over PVT unless noted"
    ]
    assert len(captions) == 1
    assert captions[0].top < graphic_frame.top


def test_table_row_wider_than_headers_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="more than"):
        render(
            [
                {
                    "type": "table",
                    "headers": ["A", "B"],
                    "rows": [["x", "y", "z"]],
                }
            ],
            None,
            tmp_path / "deck.pptx",
        )


def test_table_without_headers_uses_row_shape(tmp_path: Path) -> None:
    slide = _render_table({"type": "table", "rows": [["a", "b"], ["c", "d"]]}, tmp_path)
    (table,) = [shape.table for shape in _table_shapes(slide)]
    assert (len(table.rows), len(table.columns)) == (2, 2)
    assert table.cell(0, 1).text == "b"
