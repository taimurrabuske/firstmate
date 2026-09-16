"""OOXML and DrawingML namespace and schema constants for presenter.

Defines the Microsoft standard extension URI and namespaces for embedding
SVG vector pictures with raster fallbacks in OpenXML presentations.
"""

from __future__ import annotations

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
]

#: Standard Microsoft OpenXML extension URI for SVG picture blip extensions.
#: Documented in the Open XML SDK (Office 2019+).
SVG_EXTENSION_URI = "{96DAC541-7B7A-43D3-8B79-37D633B846F1}"

#: MIME content types for images in OOXML packages.
CONTENT_TYPE_SVG = "image/svg+xml"
CONTENT_TYPE_PNG = "image/png"

#: OOXML relationship type for image parts.
RELATIONSHIP_TYPE_IMAGE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
)

#: XML namespaces.
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_ASVG = "http://schemas.microsoft.com/office/drawing/2016/SVG/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
NS_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
