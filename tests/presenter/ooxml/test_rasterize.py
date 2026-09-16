"""Dependency-independent tests for presenter._ooxml.rasterize.

These tests never require a real SVG renderer: they exercise input
validation and the no-renderer-available error path by mocking every
renderer probe, and they verify dispatch by mocking one renderer as
successful. Tests that produce a real PNG through an installed renderer
live in test_rasterize_renderer.py.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from presenter._ooxml.rasterize import rasterize_svg_to_png
from presenter.core.errors import MissingRendererError

_SVG_TEXT = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="150">'
    '<rect width="300" height="150" fill="red"/>'
    '<circle cx="150" cy="75" r="40" fill="yellow"/>'
    '</svg>'
)


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


def test_rasterize_svg_to_png_dispatches_to_first_working_renderer(tmp_path) -> None:
    """Verify the returned path comes from the first renderer that reports success.

    Mocks cairosvg as available and successful so the dispatch order and
    return value are verified without needing any renderer installed.
    """
    out_png = tmp_path / "fallback.png"

    def _fake_cairosvg(svg_bytes: bytes, out_path, dpi: int) -> bool:
        out_path.write_bytes(b"not a real png, just proving dispatch")
        return True

    with (
        patch("presenter._ooxml.rasterize._rasterize_with_cairosvg", side_effect=_fake_cairosvg),
        patch("presenter._ooxml.rasterize._rasterize_with_rsvg") as rsvg_mock,
    ):
        result = rasterize_svg_to_png(_SVG_TEXT, output_path=out_png, dpi=150)

    assert result == out_png
    assert out_png.is_file()
    rsvg_mock.assert_not_called()
