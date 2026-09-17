"""Real-renderer tests for presenter._ooxml.rasterize.

Every test here calls an actually installed SVG rasterizer and inspects the
resulting PNG. They are skipped when no renderer is installed, matching the
existing pattern for optional-tool coverage elsewhere in this suite (see
tests/presenter/render_pptx/test_render_svg_blip.py's LibreOffice check).

CI provisions rsvg-convert explicitly (see .github/workflows/ci.yml) so this
module executes rather than skips in the presenter pytest job; presenter/README.md
documents that installation path and the alternatives for local development.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from presenter._ooxml.rasterize import (
    available_rasterizers,
    is_rasterizer_available,
    rasterize_svg_to_png,
)

pytestmark = [
    pytest.mark.svg_renderer,
    pytest.mark.skipif(
        not is_rasterizer_available(),
        reason="No SVG rasterizer installed (see presenter/README.md 'SVG rasterization')",
    ),
]

_SVG_TEXT = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="150">'
    '<rect width="300" height="150" fill="red"/>'
    '<circle cx="150" cy="75" r="40" fill="yellow"/>'
    '</svg>'
)


def test_available_rasterizers() -> None:
    """Verify rasterizer discovery returns at least one detected tool."""
    avail = available_rasterizers()
    assert isinstance(avail, tuple)
    assert avail


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


@pytest.mark.parametrize("renderer", ["cairosvg", "rsvg-convert", "inkscape"])
def test_exact_pixel_width_uses_each_available_vector_renderer(tmp_path, monkeypatch, renderer):
    import presenter._ooxml.rasterize as rasterizers

    if renderer not in available_rasterizers():
        pytest.skip(f"{renderer} is not installed")
    helpers = {"cairosvg": "_rasterize_with_cairosvg", "rsvg-convert": "_rasterize_with_rsvg",
               "inkscape": "_rasterize_with_inkscape"}
    for name, helper in helpers.items():
        if name != renderer:
            monkeypatch.setattr(rasterizers, helper, lambda *args, **kwargs: False)
    result = rasterize_svg_to_png(_SVG_TEXT.encode(), tmp_path / "sized.png", dpi=96, output_width=1200)
    with Image.open(result) as img:
        assert img.size == (1200, 600)


def test_rasterize_svg_to_png_from_bytes() -> None:
    """Verify rasterizing SVG from raw bytes without specifying output_path."""
    svg_bytes = _SVG_TEXT.encode("utf-8")
    result = rasterize_svg_to_png(svg_bytes)
    assert result.is_file()
    with Image.open(result) as img:
        assert img.format == "PNG"
    result.unlink()
