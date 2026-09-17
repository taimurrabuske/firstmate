"""JSON-safe circuit provenance and content-addressed asset bindings.

The closed producer payload is authoritative, not captions or image filenames.
Digests detect stale data/assets, not the trustworthiness of an arbitrary author.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from presenter.core.errors import CircuitFigureError


def json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CircuitFigureError(
            f"Circuit evidence must be finite JSON data: {exc}"
        ) from exc


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def content_digests(payload: dict[str, Any], source: dict[str, Any]) -> dict[str, str]:
    request = payload["request"]
    children = request.get("children", {})
    documents = {"": payload["document"], **children}
    annotations = {
        name: {
            key: value
            for key, value in doc["schematic"].items()
            if key not in {"components", "wires", "properties"}
        }
        for name, doc in documents.items()
    }
    parts = {
        "source": source,
        "symbols": payload["symbols"],
        "selected_occurrence": request.get("selected_path", []),
        "hierarchy": {"children": children, "connectivity": payload["connectivity"]},
        "annotations": {
            "documents": annotations,
            "overlays": request.get("overlays", []),
            "metadata": request.get("metadata", {}),
        },
        "analyses": {"documents": documents, "metadata": request.get("metadata", {})},
        "producer_payload": payload,
    }
    return {key: digest(json_bytes(value)) for key, value in parts.items()}


def validate_origin(
    value: Any, block: Mapping[str, Any] | None = None, *, check_files: bool = False
) -> dict[str, Any]:
    """Detach and validate the evidence, optionally checking bound local bytes."""
    try:
        origin = json.loads(json_bytes(value))
        if not isinstance(origin, dict) or set(origin) != {
            "version",
            "producer",
            "source",
            "payload",
            "digests",
            "assets",
            "width_in",
            "dpi",
            "binding_digest",
        }:
            raise ValueError("expected the complete circuit-origin v1 structure")
        binding = {key: item for key, item in origin.items() if key != "binding_digest"}
        if origin["binding_digest"] != digest(json_bytes(binding)):
            raise ValueError("circuit binding digest mismatch; regenerate the figure")
        if (
            type(origin["version"]) is not int
            or origin["version"] != 1
            or origin["producer"] not in {"schematic", "canvas"}
        ):
            raise ValueError("unsupported circuit-origin version or producer")
        width = origin["width_in"]
        if (
            isinstance(width, bool)
            or not isinstance(width, (float, int))
            or not math.isfinite(width)
            or width <= 0
        ):
            raise ValueError("width_in must be finite and positive")
        if type(origin["dpi"]) is not int or origin["dpi"] < 72:
            raise ValueError("dpi must be an integer of at least 72")
        if not isinstance(origin["source"], dict):
            raise TypeError("source must be a schematic-document envelope")
        if origin["digests"] != content_digests(origin["payload"], origin["source"]):
            raise ValueError("circuit evidence digest mismatch; regenerate the figure")
        if set(origin["assets"]) != {"svg", "png"}:
            raise ValueError("circuit figures require both SVG and PNG assets")
        for fmt, asset in origin["assets"].items():
            if (
                set(asset) != {"path", "sha256"}
                or not isinstance(asset["path"], str)
                or not asset["path"]
            ):
                raise ValueError(f"invalid {fmt} asset binding")
            sha = asset["sha256"]
            if (
                not isinstance(sha, str)
                or len(sha) != 64
                or any(c not in "0123456789abcdef" for c in sha)
            ):
                raise ValueError(f"invalid {fmt} content digest")
            if check_files and digest(Path(asset["path"]).read_bytes()) != sha:
                raise ValueError(
                    f"stale {fmt} asset at {asset['path']}; regenerate the figure"
                )
        if block is not None:
            expected = {
                "source": origin["assets"]["svg"]["path"],
                "svg": origin["assets"]["svg"]["path"],
                "fallback": origin["assets"]["png"]["path"],
            }
            for key, path in expected.items():
                if block.get(key) != path:
                    raise ValueError(
                        f"{key} does not match its circuit-origin asset binding"
                    )
            if block.get("png", expected["fallback"]) != expected["fallback"]:
                raise ValueError("png does not match its circuit-origin asset binding")
            if block.get("width_in") != width:
                raise ValueError(
                    "width_in differs from the prepared circuit figure; regenerate at the new size"
                )
        return origin
    except CircuitFigureError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, OSError) as exc:
        raise CircuitFigureError(f"Invalid circuit-origin evidence: {exc}") from exc


def verify_circuit_blocks(document: Mapping[str, Any]) -> None:
    """Verify resolved assets before dispatch; never render a stale fallback."""
    for slide in document.get("slides", []):
        for block in slide.get("blocks", []):
            if block.get("circuit_origin") is not None:
                validate_origin(block["circuit_origin"], block, check_files=True)
