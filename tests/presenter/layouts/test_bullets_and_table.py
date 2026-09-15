"""Tests for presenter.layouts.bullets_and_table."""

from __future__ import annotations

import pytest

from presenter.layouts import bullets_and_table


def test_table_on_right_by_default() -> None:
    slide = bullets_and_table(
        "Electrical characteristics",
        ["Meets spec across PVT"],
        ["Parameter", "Min", "Typ", "Max"],
        [["Vout", 3.234, 3.3, 3.366]],
        table_caption="Over PVT unless noted",
    )
    assert slide["layout"] == "Two Content"
    assert slide["blocks"][0]["type"] == "text"
    table_block = slide["blocks"][1]
    assert table_block["type"] == "table"
    assert table_block["headers"] == ["Parameter", "Min", "Typ", "Max"]
    assert table_block["rows"] == [["Vout", 3.234, 3.3, 3.366]]
    assert table_block["caption"] == "Over PVT unless noted"
    assert slide["placeholder_roles"] == {"left": [0], "right": [1]}


def test_table_on_left_when_requested() -> None:
    slide = bullets_and_table(
        "Electrical characteristics",
        ["Bullet"],
        ["Parameter", "Min"],
        [["Vout", 3.234]],
        side="left",
    )
    assert slide["blocks"][0]["type"] == "table"
    assert slide["blocks"][1]["type"] == "text"
    assert slide["placeholder_roles"] == {"left": [0], "right": [1]}


def test_mismatched_row_length_rejected() -> None:
    with pytest.raises(ValueError, match="table_rows\\[0\\]"):
        bullets_and_table(
            "Electrical characteristics",
            ["Bullet"],
            ["Parameter", "Min"],
            [["Vout"]],
        )


def test_empty_headers_rejected() -> None:
    with pytest.raises(ValueError, match="table_headers"):
        bullets_and_table("Electrical characteristics", ["Bullet"], [], [])
