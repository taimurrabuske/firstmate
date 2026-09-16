"""Tests for presenter._ooxml.rasterize module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from presenter._ooxml.rasterize import (
    available_rasterizers,
    is_rasterizer_available,
    rasterize_svg_to_png,
)
from presenter.core.errors import MissingRendererError

_SVG_TEXT = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="150">'
    '<rect width="300" height="150" fill="red"/>'
    '<circle cx="150" cy="75" r="40" fill="yellow"/>'
    '</svg>'
)


def test_available_rasterizers() -> None:
    """Verify rasterizer discovery returns detected tools."""
    avail = available_rasterizers()
    assert isinstance(avail, tuple)
    # On this environment, inkscape and/or convert are available
    assert is_rasterizer_available() is True


def test_rasterize_svg_to_png_from_text(tmp_path: Path) -> None:
    """Verify rasterizing SVG XML string to PNG fallback."""
    out_png = tmp_path / "fallback.png"
    result = rasterize_svg_to_png(_SVG_TEXT, output_path=out_png, dpi=300)

    assert result == out_png
    assert out_png.is_file()
    assert out_png.stat().st_size > 0

    with Image.open(out_png) as img:
        assert img.format == "PNG"
        assert img.width > 0
        assert img.height > 0


def test_rasterize_svg_to_png_from_file(tmp_path: Path) -> None:
    """Verify rasterizing SVG from an existing filesystem file."""
    svg_file = tmp_path / "graphic.svg"
    svg_file.write_text(_SVG_TEXT, encoding="utf-8")

    result = rasterize_svg_to_png(svg_file, dpi=200)
    assert result.is_file()
    with Image.open(result) as img:
        assert img.format == "PNG"
    result.unlink()


def test_rasterize_svg_to_png_from_bytes() -> None:
    """Verify rasterizing SVG from raw bytes without specifying output_path."""
    svg_bytes = _SVG_TEXT.encode("utf-8")
    result = rasterize_svg_to_png(svg_bytes)
    assert result.is_file()
    with Image.open(result) as img:
        assert img.format == "PNG"
    result.unlink()


def test_rasterize_svg_missing_renderer_error() -> None:
    """Verify MissingRendererError is raised when no renderer is available."""
    with (
        patch("shutil.which", return_value=None),
        patch("presenter._ooxml.rasterize._rasterize_with_cairosvg", return_value=False),
        pytest.raises(MissingRendererError, match="Rasterizing SVG to PNG fallback requires"),
    ):
        rasterize_svg_to_png(_SVG_TEXT)


def test_rasterize_svg_invalid_input_type() -> None:
    """Verify TypeError or ValueError for unsupported SVG input."""
    with pytest.raises(ValueError, match="Unsupported SVG input type"):
        rasterize_svg_to_png(12345)  # type: ignore[arg-type]
