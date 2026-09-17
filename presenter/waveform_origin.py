"""Portable waveform-origin v1 evidence, independent of Qt and Python 3.12.

The producer owns scientific selection and rendering. This envelope retains its
closed bundle verbatim (base64 for lossless IEEE arrays), caller assertions and
versioned read disclosure. Hashes prove integrity, not author authenticity.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import re
import struct
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from presenter.core.errors import WaveformFigureError

SCHEMA = "presenter.waveform-origin/v1"
PRODUCER_SCHEMA = "waveforms-widgets.native-figure/v1"


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
        raise WaveformFigureError(
            f"Waveform evidence must be JSON-safe: {exc}"
        ) from exc


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_loads(data: bytes | str) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate evidence JSON key")
            result[key] = value
        return result

    return json.loads(data, object_pairs_hook=unique)


def _closed(value: Any, keys: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("missing or unknown evidence fields")


def safe_svg(data: bytes) -> None:
    """Reject active content and all external references before Office dispatch."""
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)|<\?xml-stylesheet", data, re.IGNORECASE):
        raise ValueError("SVG DTD/entity references are unsafe")
    root = ET.fromstring(data)
    if root.tag != "{http://www.w3.org/2000/svg}svg":
        raise ValueError("expected SVG document")
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1].lower()
        if tag in {
            "script",
            "foreignobject",
            "image",
            "set",
            "discard",
        } or tag.startswith("animate"):
            raise ValueError("unsafe active or external SVG content")
        if tag == "style" and (
            "\\" in (node.text or "")
            or re.search(
                r"@|url\s*\(|expression|behavior", node.text or "", re.IGNORECASE
            )
        ):
            raise ValueError("unsafe SVG stylesheet")
        for key, value in node.attrib.items():
            name = key.rsplit("}", 1)[-1].lower()
            if (
                name.startswith("on")
                or name == "base"
                or "\\" in value
                or (name in {"href", "src"} and not value.startswith("#"))
            ):
                raise ValueError("unsafe external SVG reference")
            for target in re.findall(r"url\s*\((.*?)\)", value, re.IGNORECASE):
                if not target.strip().strip("'\"").startswith("#"):
                    raise ValueError("unsafe external SVG URL")
            if name == "style" and re.search(
                r"@|expression|behavior", value, re.IGNORECASE
            ):
                raise ValueError("unsafe SVG style")


def _nonfinite(array: np.ndarray) -> dict[str, int]:
    values = (
        np.concatenate((array.real.ravel(), array.imag.ravel()))
        if np.iscomplexobj(array)
        else array
    )
    return {
        key: int(fn(values).sum()) if values.dtype.kind == "f" else 0
        for key, fn in (
            ("nan", np.isnan),
            ("positive_infinity", np.isposinf),
            ("negative_infinity", np.isneginf),
        )
    }


def _bundle(payload: dict, members: dict) -> dict[str, bytes]:
    """Check the delivered producer schema without importing optional libraries."""
    _closed(
        payload,
        {
            "schema",
            "request",
            "dimensions",
            "array_encoding",
            "inputs",
            "selected",
            "geometry",
            "representations",
            "evidence_sha256",
        },
    )
    if payload["schema"] != PRODUCER_SCHEMA:
        raise ValueError("unsupported native producer schema")
    if (
        digest(json_bytes({k: v for k, v in payload.items() if k != "evidence_sha256"}))
        != payload["evidence_sha256"]
    ):
        raise ValueError("producer binding mismatch")
    if (
        payload["array_encoding"]
        != "npy-no-pickle; IEEE nonfinite values are gaps; complex components are lossless"
    ):
        raise ValueError("unsupported array encoding")
    request = payload["request"]
    _closed(
        request,
        {
            "kind",
            "part",
            "members",
            "max_curves",
            "interpolation",
            "title",
            "xlabel",
            "ylabel",
            "xlim",
            "ylim",
            "xscale",
            "yscale",
            "theme",
            "colors",
            "line_width_pt",
            "font_size_pt",
            "width_in",
            "height_in",
            "dpi",
        },
    )
    if (
        request["kind"] != "analog-cartesian"
        or request["part"] not in {"mag", "real", "imag", "phase", "db10", "db20"}
        or request["interpolation"] not in (None, "linear", "step")
        or any(request[k] not in ("linear", "log") for k in ("xscale", "yscale"))
    ):
        raise ValueError("unsupported native semantics")
    if type(request["max_curves"]) is not int or not 1 <= request["max_curves"] <= 256:
        raise ValueError("invalid curve cap")
    for key in ("width_in", "height_in", "line_width_pt", "font_size_pt"):
        if (
            isinstance(request[key], bool)
            or not isinstance(request[key], (int, float))
            or not math.isfinite(request[key])
            or request[key] <= 0
        ):
            raise ValueError(f"invalid {key}")
    if type(request["dpi"]) is not int or not 36 <= request["dpi"] <= 1200:
        raise ValueError("invalid DPI")
    dims = [round(request[k] * request["dpi"]) for k in ("width_in", "height_in")]
    if (
        payload["dimensions"] != dims
        or math.prod(dims) > 100_000_000
        or any(not 2 <= request[k] <= 30 for k in ("width_in", "height_in"))
    ):
        raise ValueError("physical dimensions disagree or exceed rendering budget")
    if (
        not isinstance(request["title"], str)
        or not isinstance(request["theme"], str)
        or not request["theme"]
        or any(
            request[k] is not None and not isinstance(request[k], str)
            for k in ("xlabel", "ylabel")
        )
    ):
        raise ValueError("invalid render labels/theme")
    if (
        not isinstance(request["colors"], list)
        or not request["colors"]
        or any(
            not isinstance(c, str) or re.fullmatch(r"#[0-9a-fA-F]{6}", c) is None
            for c in request["colors"]
        )
    ):
        raise ValueError("invalid render colors")
    for key, scale in (("xlim", "xscale"), ("ylim", "yscale")):
        limits = request[key]
        if limits is not None and (
            not isinstance(limits, list)
            or len(limits) != 2
            or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) for v in limits
            )
            or limits[0] >= limits[1]
            or (request[scale] == "log" and limits[0] <= 0)
        ):
            raise ValueError("invalid render bounds")
    if any(
        not isinstance(payload[k], list) for k in ("inputs", "selected", "geometry")
    ) or not isinstance(members, dict):
        raise ValueError("invalid bundle collections")
    if request["members"] is not None and (
        not isinstance(request["members"], list)
        or len(request["members"]) != len(payload["inputs"])
        or any(not isinstance(group, list) or not group for group in request["members"])
    ):
        raise ValueError("invalid member selection groups")
    blobs = {}

    def checked(record: dict, array: bool = False):
        _closed(
            record,
            {"file", "sha256", "bytes", "dtype", "shape", "nonfinite"}
            if array
            else {"file", "sha256", "bytes"},
        )
        name = record["file"]
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", name)
            or name in {".", "..", "manifest.json"}
            or name in blobs
            or (array and not name.endswith(".npy"))
        ):
            raise ValueError("invalid or duplicate bundle member")
        data = base64.b64decode(members[name], validate=True)
        if (
            type(record["bytes"]) is not int
            or len(data) != record["bytes"]
            or digest(data) != record["sha256"]
        ):
            raise ValueError("mutated waveform payload member")
        blobs[name] = data
        if not array:
            return data
        _closed(record["nonfinite"], {"nan", "positive_infinity", "negative_infinity"})
        if (
            not isinstance(record["shape"], list)
            or any(type(n) is not int or n < 0 for n in record["shape"])
            or any(type(n) is not int or n < 0 for n in record["nonfinite"].values())
        ):
            raise ValueError("invalid array descriptor types")
        stream = io.BytesIO(data)
        value = np.load(stream, allow_pickle=False)
        if (
            not isinstance(value, np.ndarray)
            or value.dtype.kind not in "biufcUS"
            or value.dtype.str != record["dtype"]
            or list(value.shape) != record["shape"]
            or _nonfinite(value) != record["nonfinite"]
            or stream.read()
        ):
            raise ValueError("array descriptor mismatch")
        return value

    _closed(payload["representations"], {"svg", "png"})
    for kind, record in payload["representations"].items():
        if record["file"] != f"figure.{kind}":
            raise ValueError("representation member mismatch")
        data = checked(record)
        if kind == "svg":
            safe_svg(data)
            root = ET.fromstring(data)
            if (
                root.get("width") != f"{request['width_in']}in"
                or root.get("height") != f"{request['height_in']}in"
                or [float(v) for v in root.attrib["viewBox"].split()] != [0, 0, *dims]
            ):
                raise ValueError("SVG dimensions mismatch")
        else:
            if (
                data[:8] != b"\x89PNG\r\n\x1a\n"
                or list(struct.unpack(">II", data[16:24])) != dims
            ):
                raise ValueError("PNG dimensions mismatch")
            from PIL import Image

            with Image.open(io.BytesIO(data)) as image:
                if any(
                    abs(v - request["dpi"]) > 0.1 for v in image.info.get("dpi", (0, 0))
                ):
                    raise ValueError("PNG DPI mismatch")
                image.verify()
    pairs = []
    for i, entry in enumerate(payload["inputs"]):
        _closed(
            entry,
            {"input", "identity", "available", "requested", "selected", "omitted"},
        )
        _closed(entry["identity"], {"source", "result", "signal"})
        count = entry["available"]
        if (
            type(count) is not int
            or count < 1
            or type(entry["input"]) is not int
            or entry["input"] != i
            or any(
                not isinstance(entry[k], list)
                for k in ("requested", "selected", "omitted")
            )
            or count > len(entry["requested"]) + len(entry["omitted"])
        ):
            raise ValueError("invalid input disclosure")
        wanted = (
            list(range(count)) if request["members"] is None else request["members"][i]
        )
        if len(set(wanted)) != len(wanted) or any(
            type(n) is not int or not 0 <= n < count for n in wanted
        ):
            raise ValueError("invalid selection")
        selected = wanted[: max(0, request["max_curves"] - len(pairs))]
        if (
            entry["requested"] != wanted
            or entry["selected"] != selected
            or entry["omitted"] != [n for n in range(count) if n not in selected]
        ):
            raise ValueError("selection/cap disclosure mismatch")
        pairs.extend((i, n) for n in selected)
    if [(r["input"], r["member"]) for r in payload["selected"]] != pairs or not pairs:
        raise ValueError("selected members disagree")
    for row in payload["selected"]:
        _closed(
            row,
            {
                "input",
                "member",
                "coordinates",
                "xlabels",
                "xunits",
                "ylabel",
                "yunit",
                "source_interpolation",
                "interpolation",
                "display_hint",
                "signed",
                "bus_width",
                "x",
                "y",
                "outer",
            },
        )
        if (
            type(row["input"]) is not int
            or type(row["member"]) is not int
            or row["signed"] is not False
            or row["bus_width"] is not None
            or row["display_hint"] not in (None, "", "analog")
            or row["source_interpolation"] not in ("linear", "step")
            or row["interpolation"]
            != (request["interpolation"] or row["source_interpolation"])
        ):
            raise ValueError("unsupported digital/interpolation semantics")
        x, y = checked(row["x"], True), checked(row["y"], True)
        if (
            x.ndim != 1
            or y.shape != x.shape
            or x.size < 2
            or x.dtype.kind not in "iuf"
            or y.dtype.kind not in "iufc"
            or not np.isfinite(x).all()
            or not np.all(x[1:] > x[:-1])
        ):
            raise ValueError("invalid original samples")
        if (
            any(
                not isinstance(row[k], list)
                for k in ("outer", "coordinates", "xlabels", "xunits")
            )
            or any(type(i) is not int or i < 0 for i in row["coordinates"])
            or any(
                not isinstance(v, str) for k in ("xlabels", "xunits") for v in row[k]
            )
            or any(
                row[k] is not None and not isinstance(row[k], str)
                for k in ("ylabel", "yunit")
            )
            or len(row["outer"]) != len(row["coordinates"])
            or len(row["xlabels"]) != len(row["outer"]) + 1
            or len(row["xunits"]) != len(row["xlabels"])
        ):
            raise ValueError("invalid member axes")
        for outer in row["outer"]:
            if checked(outer, True).shape != (1,):
                raise ValueError("invalid family coordinate")
    if set(blobs) != set(members) or len(payload["geometry"]) != len(pairs):
        raise ValueError("closed bundle membership mismatch")
    for row in payload["geometry"]:
        _closed(
            row,
            {"vertices", "vertex_quota", "kind", "x_extent", "x_window", "y_window"},
        )
        if (
            type(row["vertices"]) is not int
            or type(row["vertex_quota"]) is not int
            or not 2 <= row["vertices"] <= row["vertex_quota"]
            or not isinstance(row["kind"], str)
        ):
            raise ValueError("invalid native geometry disclosure")
        for key in ("x_extent", "x_window", "y_window"):
            bounds = row[key]
            if (
                not isinstance(bounds, list)
                or len(bounds) != 2
                or any(
                    isinstance(v, bool) or not isinstance(v, (int, float))
                    for v in bounds
                )
                or bounds[0] > bounds[1]
            ):
                raise ValueError("invalid geometry bounds")
    return blobs


def validate_origin(
    value: Any, block: Mapping[str, Any] | None = None, *, check_files: bool = False
) -> dict:
    """Detach evidence and reject stale bindings, members and unsafe visuals."""
    try:
        origin = json.loads(json_bytes(value))
        _closed(
            origin,
            {
                "schema",
                "producer_versions",
                "identities",
                "read_disclosure",
                "payload",
                "members",
                "assets",
                "width_in",
                "height_in",
                "dpi",
                "binding_digest",
            },
        )
        if origin["schema"] != SCHEMA:
            raise ValueError("unsupported waveform-origin schema")
        if origin["binding_digest"] != digest(
            json_bytes({k: v for k, v in origin.items() if k != "binding_digest"})
        ):
            raise ValueError("waveform binding digest mismatch; regenerate the figure")
        _closed(
            origin["producer_versions"], {"presenter", "waveforms", "waveforms-widgets"}
        )
        if any(
            not isinstance(v, str) or not v
            for v in origin["producer_versions"].values()
        ):
            raise ValueError("missing producer version")
        blobs = _bundle(origin["payload"], origin["members"])
        if len(origin["identities"]) != len(origin["payload"]["inputs"]):
            raise ValueError("identity count mismatch")
        for identity, row in zip(origin["identities"], origin["payload"]["inputs"]):
            _closed(identity, {"source", "run", "result", "signal"})
            if any(
                v is not None and (not isinstance(v, str) or not v)
                for v in identity.values()
            ):
                raise ValueError("identities must be nonempty strings or null")
            if {k: identity[k] for k in ("source", "result", "signal")} != row[
                "identity"
            ]:
                raise ValueError("producer identities disagree")
        _closed(origin["read_disclosure"], {"scope", "caller"})
        if (
            origin["read_disclosure"]["scope"]
            != "selected-original-members; upstream read extent unspecified; omitted members not fingerprinted"
            or not isinstance(origin["read_disclosure"]["caller"], dict)
        ):
            raise ValueError("invalid read disclosure")
        for k in ("width_in", "height_in", "dpi"):
            if origin[k] != origin["payload"]["request"][k]:
                raise ValueError("render dimensions mismatch")
        _closed(origin["assets"], {"svg", "png"})
        for kind, asset in origin["assets"].items():
            _closed(asset, {"path", "sha256"})
            if (
                not isinstance(asset["path"], str)
                or not asset["path"]
                or asset["sha256"] != digest(blobs[f"figure.{kind}"])
            ):
                raise ValueError("invalid representation binding")
            if check_files:
                path = Path(asset["path"])
                if path.is_symlink() or path.read_bytes() != blobs[f"figure.{kind}"]:
                    raise ValueError(f"mutated {kind} reference")
        if block is not None:
            for key, kind in (("source", "svg"), ("svg", "svg"), ("fallback", "png")):
                if block.get(key) != origin["assets"][kind]["path"]:
                    raise ValueError(f"{key} does not match waveform-origin binding")
            if (
                block.get("png", origin["assets"]["png"]["path"])
                != origin["assets"]["png"]["path"]
            ):
                raise ValueError("png does not match waveform-origin binding")
            if block.get("width_in") != origin["width_in"]:
                raise ValueError(
                    "width_in changed; prepare the figure at the intended size"
                )
        return origin
    except WaveformFigureError:
        raise
    except Exception as exc:
        raise WaveformFigureError(f"Invalid waveform-origin evidence: {exc}") from exc


def extract_waveform_bundle(origin: Mapping[str, Any], directory: str | Path) -> Path:
    """Reopen original selected scientific data without source files or Qt.

    Write a new closed producer bundle, usable with Widgets' ``reopen_figure``.
    Office packages retain this envelope in their related waveform-origin part.
    """
    evidence = validate_origin(origin)
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=False)
    for name, encoded in evidence["members"].items():
        (target / name).write_bytes(base64.b64decode(encoded, validate=True))
    manifest = target / "manifest.json"
    manifest.write_bytes(json_bytes(evidence["payload"]))
    return manifest


def read_office_waveform_origins(package: str | Path) -> list[dict]:
    """Read and verify related waveform evidence from PPTX or DOCX, offline."""
    import posixpath
    import zipfile

    try:
        with zipfile.ZipFile(package) as archive:
            names = archive.namelist()
            if len(set(names)) != len(names):
                raise ValueError("duplicate Office package member")

            def related(part: str, kind: str) -> set[str]:
                relpath = posixpath.join(
                    posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels"
                )
                targets = set()
                for rel in ET.fromstring(archive.read(relpath)):
                    if rel.get("Type") != kind:
                        continue
                    if rel.get("TargetMode") == "External":
                        raise ValueError("external waveform relationship")
                    target = rel.attrib["Target"]
                    resolved = posixpath.normpath(
                        posixpath.join(posixpath.dirname(part), target)
                    ).lstrip("/")
                    if resolved.startswith("../") or "\\\\" in resolved:
                        raise ValueError("unsafe package target")
                    targets.add(resolved)
                return targets

            root = (
                "ppt/presentation.xml"
                if "ppt/presentation.xml" in names
                else "word/document.xml"
            )
            result = []
            for manifest in sorted(
                related(root, "urn:presenter:relationships:waveform-origin")
            ):
                body = _json_loads(archive.read(manifest))
                _closed(body, {"schema", "figures"})
                if body["schema"] != "presenter.waveform-package/v1":
                    raise ValueError("unsupported waveform package schema")
                linked = related(
                    manifest, "urn:presenter:relationships:waveform-member"
                )
                used = set()
                for entry in body["figures"]:
                    _closed(entry, {"block_index", "waveform_origin", "package_parts"})
                    origin = validate_origin(entry["waveform_origin"])
                    if set(entry["package_parts"]) != set(origin["members"]):
                        raise ValueError("missing packaged waveform member")
                    for name, part in entry["package_parts"].items():
                        target = part.lstrip("/")
                        if target not in linked or archive.read(
                            target
                        ) != base64.b64decode(origin["members"][name], validate=True):
                            raise ValueError("mutated/missing related waveform member")
                        used.add(target)
                    result.append(origin)
                if used != linked:
                    raise ValueError("unaccounted waveform package members")
            return result
    except WaveformFigureError:
        raise
    except Exception as exc:
        raise WaveformFigureError(f"Invalid Office waveform evidence: {exc}") from exc


def verify_waveform_blocks(document: Mapping[str, Any]) -> None:
    for slide in document.get("slides", []):
        for block in slide.get("blocks", []):
            if block.get("waveform_origin") is not None:
                validate_origin(block["waveform_origin"], block, check_files=True)
