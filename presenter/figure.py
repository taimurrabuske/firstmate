"""Figure asset representation holding vector SVG and raster PNG assets.

Follows the vector/raster asset strategy (scout report §4.1):
A Figure represents logical technical art (circuit schematics, waveform plots,
block diagrams) with one or more representations:
- SVG for pure vector line art.
- PNG for high-resolution raster fallback.
- Optional caption, alt text, physical width_in, and evidence reference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from presenter._ooxml.rasterize import rasterize_svg_to_png

__all__ = ["Figure"]


@dataclass
class Figure:
    """Figure asset holding vector SVG and/or raster PNG representations.

    Parameters:
        svg: File path (str or Path) or raw bytes of the vector SVG image.
        png: File path or raw bytes of the PNG raster fallback.
        source: Optional primary source path or evidence reference.
        caption: Optional human-readable caption.
        alt_text: Optional accessibility description.
        width_in: Intended physical display width in inches.
        representations: Optional mapping of format -> asset representations.
    """

    svg: str | Path | bytes | None = None
    png: str | Path | bytes | None = None
    source: str | Path | None = None
    caption: str | None = None
    alt_text: str | None = None
    width_in: float | None = None
    representations: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Populate svg or png from representations if provided
        if not self.svg and "svg" in self.representations:
            self.svg = self.representations["svg"]
        if not self.png and "png" in self.representations:
            self.png = self.representations["png"]
        if not self.png and "fallback" in self.representations:
            self.png = self.representations["fallback"]

        # Derive svg/png from source path extension when unspecified
        if self.source and not self.svg and not self.png:
            src_str = str(self.source).lower()
            if src_str.endswith(".svg"):
                self.svg = self.source
            elif src_str.endswith((".png", ".jpg", ".jpeg")):
                self.png = self.source

    @property
    def has_svg(self) -> bool:
        """Return True if an SVG representation is available."""
        return self.svg is not None

    @property
    def has_png(self) -> bool:
        """Return True if a PNG fallback representation is available."""
        return self.png is not None

    @property
    def fallback(self) -> str | Path | bytes | None:
        """Alias for png representation."""
        return self.png

    @fallback.setter
    def fallback(self, value: str | Path | bytes | None) -> None:
        self.png = value

    def ensure_png_fallback(self, *, dpi: int = 300) -> Path | bytes:
        """Ensure a PNG fallback exists, rasterizing SVG if necessary.

        If a PNG representation is already present, it is returned. If only SVG
        is present, it is cleanly rasterized to a high-resolution PNG fallback
        at the specified DPI and cached on this Figure instance.
        """
        if self.png is not None:
            if isinstance(self.png, (str, Path)):
                return Path(self.png)
            return self.png

        if self.svg is not None:
            png_path = rasterize_svg_to_png(self.svg, dpi=dpi)
            self.png = png_path
            return png_path

        raise ValueError("Figure has neither SVG nor PNG representation.")

    def to_block(self, block_type: str = "image") -> dict[str, Any]:
        """Convert this Figure into a validated presenter content block dict."""
        src: str = ""
        if self.svg:
            src = str(self.svg) if isinstance(self.svg, (str, Path)) else "figure.svg"
        elif self.source:
            src = str(self.source)
        elif self.png:
            src = str(self.png) if isinstance(self.png, (str, Path)) else "figure.png"

        block: dict[str, Any] = {
            "type": block_type,
            "source": src,
        }
        if self.svg is not None:
            block["svg"] = str(self.svg) if isinstance(self.svg, (str, Path)) else self.svg
        if self.png is not None:
            block["fallback"] = str(self.png) if isinstance(self.png, (str, Path)) else self.png
            block["png"] = block["fallback"]
        if self.caption is not None:
            block["caption"] = self.caption
        if self.alt_text is not None:
            block["alt_text"] = self.alt_text
        if self.width_in is not None:
            block["width_in"] = self.width_in
        return block

    def to_dict(self) -> dict[str, Any]:
        """Serialize Figure properties to a plain dictionary."""
        return {
            "source": str(self.source) if self.source else None,
            "svg": str(self.svg) if isinstance(self.svg, (str, Path)) else (self.svg is not None),
            "png": str(self.png) if isinstance(self.png, (str, Path)) else (self.png is not None),
            "caption": self.caption,
            "alt_text": self.alt_text,
            "width_in": self.width_in,
        }
