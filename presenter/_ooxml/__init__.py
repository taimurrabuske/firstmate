"""OOXML extension package for presenter."""

from __future__ import annotations

from presenter._ooxml.constants import (
    CONTENT_TYPE_PNG,
    CONTENT_TYPE_SVG,
    NS_A,
    NS_ASVG,
    NS_P,
    NS_R,
    NS_RELS,
    NS_TYPES,
    RELATIONSHIP_TYPE_IMAGE,
    SVG_EXTENSION_URI,
)
from presenter._ooxml.rasterize import (
    available_rasterizers,
    is_rasterizer_available,
    rasterize_svg_to_png,
)
from presenter._ooxml.svg import (
    add_svg_picture,
    attach_svg_blip_extension,
    ensure_svg_content_type,
    get_or_add_svg_part,
    is_svg_asset,
    relate_svg_part,
)

__all__ = [
    "CONTENT_TYPE_PNG",
    "CONTENT_TYPE_SVG",
    "NS_A",
    "NS_ASVG",
    "NS_P",
    "NS_R",
    "NS_RELS",
    "NS_TYPES",
    "RELATIONSHIP_TYPE_IMAGE",
    "SVG_EXTENSION_URI",
    "add_svg_picture",
    "attach_svg_blip_extension",
    "available_rasterizers",
    "ensure_svg_content_type",
    "get_or_add_svg_part",
    "is_rasterizer_available",
    "is_svg_asset",
    "rasterize_svg_to_png",
    "relate_svg_part",
]
