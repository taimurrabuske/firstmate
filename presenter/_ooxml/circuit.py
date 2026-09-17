"""Retain circuit sources/evidence as related OPC parts in both Office formats."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from presenter.circuit_origin import json_bytes, validate_origin

_REL = "urn:presenter:relationships:circuit-origin"
_ASSET_REL = "urn:presenter:relationships:circuit-representation"


def retain_circuit_evidence(
    root_part: Any, blocks: Iterable[Mapping[str, Any]], *, fmt: str
) -> None:
    """Attach a JSON manifest and the exact SVG/PNG bytes, independently of ink.

    A manifest entry identifies the flattened input block index and maps each
    representation to a package part. Original local asset bindings remain in
    the evidence for audit; package_parts are the portable retrieval addresses.
    """
    entries = []
    for index, block in enumerate(blocks):
        if block.get("circuit_origin") is not None:
            origin = validate_origin(block["circuit_origin"], block, check_files=True)
            entries.append({"block_index": index, "circuit_origin": origin})
    if not entries:
        return
    if fmt == "docx":
        from docx.opc.part import Part
    else:
        from pptx.opc.package import Part
    package = root_part.package
    # Relate first so next_partname sees all parts allocated in this operation.
    manifest = Part(
        package.next_partname("/presenter/circuit-origin%d.json"),
        "application/json",
        package=package,
        blob=b"",
    )
    root_part.relate_to(manifest, _REL)
    for entry in entries:
        parts = {}
        for kind, asset in entry["circuit_origin"]["assets"].items():
            media_type = "image/svg+xml" if kind == "svg" else "image/png"
            name = package.next_partname(f"/presenter/circuit-asset%d.{kind}")
            part = Part(
                name, media_type, package=package, blob=Path(asset["path"]).read_bytes()
            )
            manifest.relate_to(part, _ASSET_REL)
            parts[kind] = str(name)
        entry["package_parts"] = parts
    manifest._blob = json_bytes({"version": 1, "figures": entries})
