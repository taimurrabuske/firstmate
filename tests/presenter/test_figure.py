"""Tests for presenter.figure.Figure asset model."""

from __future__ import annotations

from pathlib import Path

import pytest

from presenter.core.blocks import ImageBlock, PlotBlock, validate_block
from presenter.core.spec import DocumentBuilder, SlideSpec
from presenter.figure import Figure

_SVG_STRING = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
    '<circle cx="50" cy="50" r="40" fill="green"/>'
    '</svg>'
)


def test_figure_initialization_with_svg_and_png(tmp_path: Path) -> None:
    """Verify Figure initializes with both vector SVG and raster PNG."""
    svg_p = tmp_path / "chart.svg"
    png_p = tmp_path / "chart.png"
    svg_p.write_text(_SVG_STRING)
    png_p.write_bytes(b"\x89PNG...")

    fig = Figure(
        svg=svg_p,
        png=png_p,
        caption="Transient Response",
        alt_text="A waveform diagram",
        width_in=5.0,
    )

    assert fig.has_svg is True
    assert fig.has_png is True
    assert fig.svg == svg_p
    assert fig.png == png_p
    assert fig.fallback == png_p
    assert fig.caption == "Transient Response"
    assert fig.alt_text == "A waveform diagram"
    assert fig.width_in == 5.0


def test_figure_derives_svg_or_png_from_source() -> None:
    """Verify source extension sets svg or png automatically."""
    fig_svg = Figure(source="diagram.svg")
    assert fig_svg.has_svg is True
    assert fig_svg.has_png is False
    assert fig_svg.svg == "diagram.svg"

    fig_png = Figure(source="photo.png")
    assert fig_png.has_svg is False
    assert fig_png.has_png is True
    assert fig_png.png == "photo.png"


def test_figure_representations_dict() -> None:
    """Verify representations mapping populates svg and png."""
    fig = Figure(representations={"svg": "vector.svg", "png": "raster.png"})
    assert fig.has_svg is True
    assert fig.has_png is True
    assert fig.svg == "vector.svg"
    assert fig.png == "raster.png"


def test_figure_ensure_png_fallback_existing(tmp_path: Path) -> None:
    """Verify ensure_png_fallback returns existing PNG without re-rasterizing."""
    png_p = tmp_path / "existing.png"
    png_p.write_bytes(b"\x89PNG...")
    fig = Figure(svg="something.svg", png=png_p)

    assert fig.ensure_png_fallback() == png_p


def test_figure_ensure_png_fallback_rasterizes(tmp_path: Path) -> None:
    """Verify ensure_png_fallback cleanly rasterizes SVG when PNG is missing."""
    svg_p = tmp_path / "graphic.svg"
    svg_p.write_text(_SVG_STRING)
    fig = Figure(svg=svg_p)

    assert fig.has_png is False
    fallback = fig.ensure_png_fallback()

    assert fig.has_png is True
    assert Path(fallback).is_file()
    assert Path(fallback).stat().st_size > 0
    if isinstance(fallback, Path):
        fallback.unlink()


def test_figure_ensure_png_fallback_neither_raises() -> None:
    """Verify ValueError when neither SVG nor PNG is available."""
    fig = Figure()
    with pytest.raises(ValueError, match="neither SVG nor PNG"):
        fig.ensure_png_fallback()


def test_figure_to_block() -> None:
    """Verify converting Figure to presenter block dict."""
    fig = Figure(
        svg="plot.svg",
        png="plot.png",
        caption="Gain vs Frequency",
        width_in=6.0,
        alt_text="Bode magnitude plot",
    )

    block = fig.to_block(block_type="plot")
    assert block["type"] == "plot"
    assert block["source"] == "plot.svg"
    assert block["fallback"] == "plot.png"
    assert block["svg"] == "plot.svg"
    assert block["caption"] == "Gain vs Frequency"
    assert block["width_in"] == 6.0
    assert block["alt_text"] == "Bode magnitude plot"

    # Verify validate_block accepts the output
    validated = validate_block(block)
    assert validated["type"] == "plot"
    assert validated["fallback"] == "plot.png"
    assert validated["svg"] == "plot.svg"


def test_figure_passed_directly_to_validate_block() -> None:
    """Verify validate_block accepts Figure instances directly."""
    fig = Figure(
        svg="schematic.svg",
        png="schematic.png",
        caption="LDO Regulator Core",
        width_in=4.5,
    )

    validated = validate_block(fig)
    assert validated["type"] == "image"
    assert validated["source"] == "schematic.svg"
    assert validated["fallback"] == "schematic.png"


def test_figure_with_spec_builder() -> None:
    """Verify SlideSpec and DocumentBuilder accept Figure objects."""
    fig = Figure(
        svg="waveform.svg",
        png="waveform.png",
        caption="Transient Simulation",
    )

    slide = SlideSpec(title="Results")
    slide.add_block(fig)
    assert len(slide.blocks) == 1
    assert slide.blocks[0]["type"] == "image"
    assert slide.blocks[0]["source"] == "waveform.svg"

    doc = DocumentBuilder("Deck").slide("Slide 1").add(fig).build()
    assert len(doc.slides[0].blocks) == 1


def test_image_and_plot_block_from_figure() -> None:
    """Verify ImageBlock.from_figure and PlotBlock.from_figure helpers."""
    fig = Figure(svg="view.svg", png="view.png", width_in=3.0)

    img_block = ImageBlock.from_figure(fig)
    assert img_block.source == "view.svg"
    assert img_block.fallback == "view.png"
    assert img_block.width_in == 3.0

    plot_block = PlotBlock.from_figure(fig)
    assert plot_block.source == "view.svg"
    assert plot_block.fallback == "view.png"
