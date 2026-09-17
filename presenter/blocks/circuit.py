"""Prepare a circuit-native Figure once, before generic document dispatch.

Accept a Schematic document/envelope plus explicit symbol closure, or the closed
SVG artifact exported by Canvas/Schematic. No sessions, raw netlists, palette
lookup, caption inference, or generic drawing fallback participate here.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from presenter._ooxml.rasterize import rasterize_svg_to_png
from presenter.circuit_origin import (
    content_digests,
    digest,
    json_bytes,
    validate_origin,
)
from presenter.core.errors import (
    CircuitFigureError,
    MissingRendererError,
    PresenterError,
)
from presenter.figure import Figure

if TYPE_CHECKING:
    from schematic.core.schematic_data import SchematicData
    from schematic.core.symbol_library import SymbolLibrary

__all__ = ["circuit_figure"]


def _publish(directory: Path, content: bytes, suffix: str) -> Path:
    path = directory / f"{digest(content)}.{suffix}"
    if path.exists():
        if path.read_bytes() != content:
            raise CircuitFigureError(
                f"Stale managed circuit asset {path}; remove or repair it explicitly"
            )
        return path
    fd, name = tempfile.mkstemp(dir=directory, suffix=f".{suffix}")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    return path


def circuit_figure(
    source: SchematicData | Mapping[str, Any] | str | Path | bytes,
    *,
    assets_dir: str | Path,
    symbols: SymbolLibrary | str | None = None,
    request: Mapping[str, Any] | None = None,
    width_in: float | None = None,
    dpi: int = 300,
    caption: str | None = None,
    alt_text: str | None = None,
) -> Figure:
    """Build native technical art and retain its closed evidence as JSON data.

    ``source`` is a SchematicData or schematic-document envelope with explicit
    ``symbols`` (SymbolLibrary or closed SVG definitions), or a resolved producer
    SVG (path, XML text, or bytes). Artifact requests/symbol overrides are refused.
    ``assets_dir`` owns durable, content-addressed SVG/PNG files; keep this directory
    with serialized specs. Saved Office files also contain both assets and evidence.
    Producer errors are surfaced as Presenter-root errors, never substituted art.
    """
    try:
        from schematic.core.circuit_figure import (
            export_circuit_figure,
            reopen_circuit_figure,
        )
        from schematic.core.envelope_adapter import decode_schematic_envelope
        from schematic.core.schematic_data import SchematicData
        from schematic.core.symbol_library import SymbolLibrary
    except ImportError as exc:
        raise CircuitFigureError(
            "Native circuit figures require Schematic's circuit_figure export/reopen integration "
            "and its dependencies. Install the delivered Schematic package; no generic fallback is used."
        ) from exc
    try:
        if width_in is not None and (
            isinstance(width_in, bool)
            or not isinstance(width_in, (float, int))
            or not math.isfinite(width_in)
            or width_in <= 0
        ):
            raise ValueError("width_in must be finite and positive")
        if type(dpi) is not int or dpi < 72:
            raise ValueError("dpi must be an integer of at least 72")
        if isinstance(source, (str, Path, bytes)):
            if symbols is not None or request is not None:
                raise ValueError(
                    "resolved artifacts already bind symbols and request; do not override them"
                )
            if isinstance(source, bytes):
                svg = source.decode("utf-8")
            elif isinstance(source, str) and source.lstrip().startswith("<"):
                svg = source
            else:
                svg = Path(source).read_text(encoding="utf-8")
            data, library, options = reopen_circuit_figure(svg)
            # Reopen validates the closure, not the painted SVG. Compare the actual
            # representation too, before giving any untrusted SVG to a rasterizer.
            regenerated = export_circuit_figure(data, library, request=options)
            if svg != regenerated:
                raise ValueError(
                    "resolved SVG differs from its native source binding; re-export with Canvas/Schematic"
                )
            artifact_width = (
                float(ET.fromstring(svg).attrib["width"].removesuffix("mm")) / 25.4
            )
            if width_in is not None and not math.isclose(
                width_in, artifact_width, rel_tol=1e-8
            ):
                raise ValueError(
                    "artifact width differs from width_in; re-export at the intended physical size"
                )
            width_in = artifact_width
        else:
            if symbols is None:
                raise ValueError(
                    "an explicit symbol closure is required; pass symbols=library or closed definitions"
                )
            library = (
                SymbolLibrary.from_definitions(symbols)
                if isinstance(symbols, str)
                else symbols
            )
            if not isinstance(library, SymbolLibrary):
                raise TypeError(
                    "symbols must be a Schematic SymbolLibrary or closed definitions"
                )
            data = (
                decode_schematic_envelope(dict(source))[0]
                if isinstance(source, Mapping)
                else source
            )
            if not isinstance(data, SchematicData):
                raise TypeError(
                    "source must be an explicit Schematic document/envelope or resolved figure SVG"
                )
            options = dict(request or {})
            if width_in is not None:
                if "width_mm" in options and not math.isclose(
                    options["width_mm"], width_in * 25.4
                ):
                    raise ValueError("request width_mm conflicts with width_in")
                options["width_mm"] = width_in * 25.4
            svg = export_circuit_figure(data, library, request=options)
            width_in = (
                float(ET.fromstring(svg).attrib["width"].removesuffix("mm")) / 25.4
            )
        metadata = ET.fromstring(svg).find(
            "{http://www.w3.org/2000/svg}metadata[@id='schematic-circuit-figure']"
        )
        if metadata is None or not metadata.text:
            raise ValueError("native producer did not return closed circuit metadata")
        payload = json.loads(metadata.text)
        directory = Path(assets_dir).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        svg_path = _publish(directory, svg.encode("utf-8"), "svg")
        fd, temporary = tempfile.mkstemp(dir=directory, suffix=".png")
        os.close(fd)
        try:
            # CSS points use 96 px/in inside the native viewBox. Scale the
            # viewport, not the font unit conversion, for a 300-DPI fallback.
            rasterize_svg_to_png(
                svg_path, temporary, dpi=96, output_width=round(width_in * dpi)
            )
            png_path = _publish(directory, Path(temporary).read_bytes(), "png")
        finally:
            Path(temporary).unlink(missing_ok=True)
        producer = payload["request"].get("metadata", {}).get("producer")
        source_record = (
            dict(source) if isinstance(source, Mapping) else payload["document"]
        )
        origin = {
            "version": 1,
            "producer": "canvas" if producer == "canvas" else "schematic",
            "source": source_record,
            "payload": payload,
            "digests": content_digests(payload, source_record),
            "assets": {
                fmt: {"path": str(path), "sha256": digest(path.read_bytes())}
                for fmt, path in (("svg", svg_path), ("png", png_path))
            },
            "width_in": width_in,
            "dpi": dpi,
        }
        origin["binding_digest"] = digest(json_bytes(origin))
        return Figure(
            svg=svg_path,
            png=png_path,
            width_in=width_in,
            caption=caption,
            alt_text=alt_text,
            circuit_origin=validate_origin(origin, check_files=True),
        )
    except MissingRendererError as exc:
        raise CircuitFigureError(
            "Native circuit rasterization failed. Install CairoSVG (presenter[svg]), librsvg, or Inkscape; "
            "a circuit figure requires a size-correct PNG from its bound SVG, not a replacement image."
        ) from exc
    except PresenterError:
        raise
    except Exception as exc:
        raise CircuitFigureError(
            f"Native circuit figure could not be prepared: {exc}"
        ) from exc
