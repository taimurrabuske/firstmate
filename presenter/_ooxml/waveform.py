"""Closed waveform bundles related to the Office document root, not sidecars."""

from __future__ import annotations

import base64
from collections.abc import Iterable, Mapping
from typing import Any

from presenter.waveform_origin import json_bytes, validate_origin

RELATIONSHIP = "urn:presenter:relationships:waveform-origin"
MEMBER_RELATIONSHIP = "urn:presenter:relationships:waveform-member"


def retain_waveform_evidence(
    root_part: Any, blocks: Iterable[Mapping[str, Any]], *, fmt: str
) -> None:
    entries = [
        {
            "block_index": i,
            "waveform_origin": validate_origin(
                b["waveform_origin"], b, check_files=True
            ),
        }
        for i, b in enumerate(blocks)
        if b.get("waveform_origin") is not None
    ]
    if not entries:
        return
    if fmt == "docx":
        from docx.opc.part import Part
    else:
        from pptx.opc.package import Part
    package = root_part.package
    manifest = Part(
        package.next_partname("/presenter/waveform-origin%d.json"),
        "application/json",
        package=package,
        blob=b"",
    )
    root_part.relate_to(manifest, RELATIONSHIP)
    for entry in entries:
        parts = {}
        for name, encoded in entry["waveform_origin"]["members"].items():
            extension = name.rsplit(".", 1)[-1]
            partname = package.next_partname(
                f"/presenter/waveform-member%d.{extension}"
            )
            content_type = {
                "svg": "image/svg+xml",
                "png": "image/png",
                "npy": "application/octet-stream",
            }[extension]
            part = Part(
                partname,
                content_type,
                package=package,
                blob=base64.b64decode(encoded, validate=True),
            )
            manifest.relate_to(part, MEMBER_RELATIONSHIP)
            parts[name] = str(partname)
        entry["package_parts"] = parts
    manifest._blob = json_bytes(
        {"schema": "presenter.waveform-package/v1", "figures": entries}
    )
