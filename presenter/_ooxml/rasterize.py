"""Clean SVG to PNG rasterization for Office raster fallbacks.

Provides headless SVG-to-PNG rasterization at high resolution (default 300 DPI)
using available local renderers (cairosvg, rsvg-convert, inkscape, or convert).
Raises MissingRendererError with actionable instructions when no renderer is found.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

from presenter.core.errors import MissingRendererError

__all__ = [
    "available_rasterizers",
    "is_rasterizer_available",
    "rasterize_svg_to_png",
]

_RENDERER_NAMES = ("cairosvg", "rsvg-convert", "inkscape", "convert")


def available_rasterizers() -> Sequence[str]:
    """Return names of SVG rasterizers detected in the current environment."""
    available: list[str] = []
    try:
        import cairosvg  # noqa: F401

        available.append("cairosvg")
    except ImportError:
        pass

    for cli in ("rsvg-convert", "inkscape", "convert"):
        if shutil.which(cli) is not None:
            available.append(cli)

    return tuple(available)


def is_rasterizer_available() -> bool:
    """Return True if at least one SVG rasterizer is available."""
    return bool(available_rasterizers())


def _rasterize_with_cairosvg(
    svg_bytes: bytes, out_path: Path, dpi: int, *, output_width: int | None = None
) -> bool:
    try:
        import cairosvg

        cairosvg.svg2png(bytestring=svg_bytes, write_to=str(out_path), dpi=dpi, output_width=output_width)
        return out_path.is_file() and out_path.stat().st_size > 0
    except (ImportError, OSError, ValueError):
        return False


def _rasterize_with_rsvg(
    in_path: Path, out_path: Path, dpi: int, *, output_width: int | None = None
) -> bool:
    bin_path = shutil.which("rsvg-convert")
    if not bin_path:
        return False
    try:
        cmd = [
            bin_path,
            "-d",
            str(dpi),
            "-p",
            str(dpi),
            "-f",
            "png",
            "-o",
            str(out_path),
            str(in_path),
        ]
        if output_width is not None:
            cmd[1:1] = ["--width", str(output_width)]
        res = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
        return res.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 0
    except (subprocess.SubprocessError, OSError):
        return False


def _rasterize_with_inkscape(
    in_path: Path, out_path: Path, dpi: int, *, output_width: int | None = None
) -> Path | None:
    bin_path = shutil.which("inkscape")
    if not bin_path:
        return None
    try:
        cmd = [
            bin_path,
            str(in_path),
            "--export-type=png",
            f"--export-filename={out_path}",
            f"--export-dpi={dpi}",
        ]
        if output_width is not None:
            cmd.append(f"--export-width={output_width}")
        res = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
        if res.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 0:
            return out_path
        return None
    except (subprocess.SubprocessError, OSError):
        return None


def _rasterize_with_convert(
    in_path: Path, out_path: Path, dpi: int
) -> bool:
    bin_path = shutil.which("convert")
    if not bin_path:
        return False
    try:
        cmd = [
            bin_path,
            "-density",
            str(dpi),
            str(in_path),
            str(out_path),
        ]
        res = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
        return res.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 0
    except (subprocess.SubprocessError, OSError):
        return False


def rasterize_svg_to_png(
    svg_input: str | Path | bytes,
    output_path: str | Path | None = None,
    *,
    dpi: int = 300,
    output_width: int | None = None,
) -> Path:
    """Rasterize an SVG representation to a high-resolution PNG fallback.

    Args:
        svg_input: Path to SVG file, SVG XML string, or raw SVG bytes.
        output_path: Destination PNG path. If None, creates a temporary file.
        dpi: SVG physical-unit conversion DPI (default 300).
        output_width: Optional final pixel width, preserving aspect ratio. For
            SVGs with physical font units inside a viewBox, use dpi=96 and scale
            via this field so high-resolution output does not enlarge the fonts.
            Requires CairoSVG, librsvg, or Inkscape (not a bitmap resize).

    Returns:
        Path to the generated PNG image.

    Raises:
        MissingRendererError: When no SVG rasterizer is available or all fail.
    """
    if output_width is not None and (type(output_width) is not int or output_width <= 0):
        raise ValueError("output_width must be a positive integer")
    sizing = {} if output_width is None else {"output_width": output_width}
    # Extract raw bytes and source path if existing
    temp_in: Path | None = None
    if isinstance(svg_input, (str, Path)) and Path(svg_input).is_file():
        in_path = Path(svg_input).resolve()
        svg_bytes = in_path.read_bytes()
    else:
        if isinstance(svg_input, str):
            svg_bytes = svg_input.encode("utf-8")
        elif isinstance(svg_input, bytes):
            svg_bytes = svg_input
        else:
            raise ValueError(f"Unsupported SVG input type: {type(svg_input).__name__}")
        fd, tmp_svg = tempfile.mkstemp(prefix="presenter_svg_", suffix=".svg")
        os.close(fd)
        temp_in = Path(tmp_svg)
        temp_in.write_bytes(svg_bytes)
        in_path = temp_in

    # Prepare output path
    if output_path is not None:
        target_out = Path(output_path).resolve()
        target_out.parent.mkdir(parents=True, exist_ok=True)
    else:
        fd, tmp_png = tempfile.mkstemp(prefix="presenter_png_", suffix=".png")
        os.close(fd)
        target_out = Path(tmp_png).resolve()

    try:
        # 1. Try cairosvg (pure python binding)
        if _rasterize_with_cairosvg(svg_bytes, target_out, dpi, **sizing):
            return target_out

        # 2. Try rsvg-convert (fast CLI)
        if _rasterize_with_rsvg(in_path, target_out, dpi, **sizing):
            return target_out

        # 3. Try inkscape (modern standard)
        if _rasterize_with_inkscape(in_path, target_out, dpi, **sizing):
            return target_out

        # 4. Try ImageMagick convert
        if output_width is None and _rasterize_with_convert(in_path, target_out, dpi):
            return target_out

        # If we reach here, no renderer succeeded
        avail = available_rasterizers()
        detail = (
            f"Detected renderers {avail} failed to process SVG"
            if avail
            else "No SVG rasterizer installed"
        )
        raise MissingRendererError(
            f"{detail}. Rasterizing SVG to PNG fallback requires an installed renderer "
            "(cairosvg, rsvg-convert, inkscape, or imagemagick convert). "
            "Provide an explicit PNG fallback or install a supported rasterizer."
        )
    finally:
        if temp_in is not None and temp_in.exists():
            try:
                temp_in.unlink()
            except OSError:
                pass
