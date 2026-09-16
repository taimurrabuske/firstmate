"""OOXML SVG picture packaging with asvg:svgBlip DrawingML extension.

Implements dual-relationship picture packaging per Microsoft Open XML SDK
specifications (Office 2019+):
- Ordinary a:blip pointing to the raster PNG fallback media part.
- Extension a:ext ({96DAC541-7B7A-43D3-8B79-37D633B846F1}) with asvg:svgBlip
  pointing to the vector SVG media part.
- Automatic content-type registration ([Content_Types].xml).
- Digest-based media part deduplication.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any

from pptx.opc import serialized
from pptx.opc.package import PackURI, Part
from pptx.oxml import parse_xml

from presenter._ooxml.constants import (
    CONTENT_TYPE_SVG,
    NS_A,
    NS_ASVG,
    NS_R,
    RELATIONSHIP_TYPE_IMAGE,
    SVG_EXTENSION_URI,
)

__all__ = [
    "add_svg_picture",
    "attach_svg_blip_extension",
    "ensure_svg_content_type",
    "get_or_add_svg_part",
    "is_svg_asset",
    "relate_svg_part",
]


def is_svg_asset(source: str | Path | bytes) -> bool:
    """Return True if source represents an SVG file or SVG content."""
    if isinstance(source, bytes):
        head = source[:256].strip()
        return head.startswith((b"<?xml", b"<svg")) or b"<svg" in head
    s = str(source).lower()
    if s.endswith(".svg"):
        return True
    p = Path(source)
    if p.is_file():
        try:
            head = p.read_bytes()[:256].strip()
            return head.startswith((b"<?xml", b"<svg")) or b"<svg" in head
        except (OSError, UnicodeDecodeError):
            pass
    return False


def ensure_svg_content_type() -> None:
    """Ensure ('svg', 'image/svg+xml') is registered in default_content_types.

    This ensures that serialized PPTX packages automatically include:
    <Default Extension="svg" ContentType="image/svg+xml"/>
    in [Content_Types].xml.
    """
    entry = ("svg", CONTENT_TYPE_SVG)
    if entry not in serialized.default_content_types:
        serialized.default_content_types = serialized.default_content_types + (entry,)


# Ensure registered on module load
ensure_svg_content_type()


def _next_svg_partname(package: Any, cache: dict[str, Part]) -> PackURI:
    """Allocate the next available /ppt/media/image%d.svg partname."""
    prefix = "/ppt/media/image"
    existing = {
        p.partname
        for p in package.iter_parts()
        if str(p.partname).startswith(prefix)
    }
    existing.update(p.partname for p in cache.values())
    n = 1
    while True:
        candidate = PackURI(f"/ppt/media/image{n}.svg")
        if candidate not in existing:
            return candidate
        n += 1


def get_or_add_svg_part(package: Any, svg_bytes: bytes) -> Part:
    """Return an SVG Part containing svg_bytes, deduplicated by sha256 digest.

    If an identical SVG payload is already stored in the package, the existing
    Part is reused to avoid duplicate media entries.
    """
    ensure_svg_content_type()
    digest = hashlib.sha256(svg_bytes).hexdigest()

    cache = getattr(package, "_svg_parts_by_hash", None)
    if cache is None:
        cache = {}
        # Pre-populate from existing parts if package was loaded from template
        try:
            for part in package.iter_parts():
                if part.content_type == CONTENT_TYPE_SVG and part.blob:
                    existing_digest = hashlib.sha256(part.blob).hexdigest()
                    cache[existing_digest] = part
        except (AttributeError, KeyError):
            pass
        package._svg_parts_by_hash = cache

    if digest in cache:
        return cache[digest]

    partname = _next_svg_partname(package, cache)
    svg_part = Part(partname, CONTENT_TYPE_SVG, package, blob=svg_bytes)
    cache[digest] = svg_part
    return svg_part


def relate_svg_part(slide_part: Any, svg_part: Part) -> str:
    """Relate an SVG Part to a slide part and return the relationship ID (rId)."""
    return slide_part.relate_to(svg_part, RELATIONSHIP_TYPE_IMAGE)


def attach_svg_blip_extension(blip_element: Any, svg_rId: str) -> None:
    """Attach the asvg:svgBlip extension to an a:blip element.

    Schema:
        <a:extLst>
          <a:ext uri="{96DAC541-7B7A-43D3-8B79-37D633B846F1}">
            <asvg:svgBlip xmlns:asvg="http://schemas.microsoft.com/office/drawing/2016/SVG/main"
                          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
                          r:embed="{svg_rId}"/>
          </a:ext>
        </a:extLst>
    """
    extLst = blip_element.find(f"{{{NS_A}}}extLst")
    if extLst is None:
        ext_xml = (
            f'<a:extLst xmlns:a="{NS_A}">'
            f'  <a:ext uri="{SVG_EXTENSION_URI}">'
            f'    <asvg:svgBlip xmlns:asvg="{NS_ASVG}" '
            f'                  xmlns:r="{NS_R}" '
            f'                  r:embed="{svg_rId}"/>'
            f"  </a:ext>"
            f"</a:extLst>"
        )
        blip_element.append(parse_xml(ext_xml))
    else:
        ext = extLst.find(f"./{{{NS_A}}}ext[@uri='{SVG_EXTENSION_URI}']")
        if ext is None:
            ext_xml = (
                f'  <a:ext xmlns:a="{NS_A}" uri="{SVG_EXTENSION_URI}">'
                f'    <asvg:svgBlip xmlns:asvg="{NS_ASVG}" '
                f'                  xmlns:r="{NS_R}" '
                f'                  r:embed="{svg_rId}"/>'
                f"  </a:ext>"
            )
            extLst.append(parse_xml(ext_xml))
        else:
            svg_blip = ext.find(f"{{{NS_ASVG}}}svgBlip")
            if svg_blip is not None:
                svg_blip.set(f"{{{NS_R}}}embed", svg_rId)
            else:
                svg_blip_xml = (
                    f'<asvg:svgBlip xmlns:asvg="{NS_ASVG}" '
                    f'              xmlns:r="{NS_R}" '
                    f'              r:embed="{svg_rId}"/>'
                )
                ext.append(parse_xml(svg_blip_xml))


def add_svg_picture(
    slide: Any,
    svg_source: str | Path | bytes,
    png_fallback: str | Path | bytes,
    left: Any,
    top: Any,
    width: Any = None,
    height: Any = None,
    *,
    alt_text: str | None = None,
) -> Any:
    """Insert a dual-relationship SVG+PNG picture into a slide.

    The picture shape displays the vector SVG in modern PowerPoint while
    maintaining full backwards compatibility through the PNG fallback.
    """
    # 1. Read SVG bytes
    if isinstance(svg_source, (str, Path)):
        svg_bytes = Path(svg_source).read_bytes()
    elif isinstance(svg_source, bytes):
        svg_bytes = svg_source
    else:
        raise TypeError(f"Unsupported SVG source type: {type(svg_source).__name__}")

    # 2. Insert PNG picture shape
    png_input: Any
    if isinstance(png_fallback, bytes):
        png_input = io.BytesIO(png_fallback)
    else:
        png_input = str(png_fallback)

    picture = slide.shapes.add_picture(
        png_input, left, top, width=width, height=height
    )

    # 3. Embed SVG part and relate to slide
    package = slide.part.package
    svg_part = get_or_add_svg_part(package, svg_bytes)
    svg_rId = relate_svg_part(slide.part, svg_part)

    # 4. Attach asvg:svgBlip extension
    attach_svg_blip_extension(picture._element.blipFill.blip, svg_rId)

    # 5. Set alt text if provided
    if alt_text:
        picture._element.nvPicPr.cNvPr.set("descr", str(alt_text))

    return picture
