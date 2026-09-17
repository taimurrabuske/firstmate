"""One lazy preparation seam over the delivered Widgets native figure producer."""

from __future__ import annotations

import base64
import importlib.metadata
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from presenter.core.errors import WaveformFigureError
from presenter.figure import Figure
from presenter.waveform_origin import SCHEMA, digest, json_bytes, validate_origin


def _native():
    if not (3, 12) <= sys.version_info[:2] < (3, 14):
        raise WaveformFigureError(
            "Native waveform figures require Python 3.12-3.13 and the delivered Waveforms/Widgets packages; "
            "ordinary assets still support Python 3.10. Request backend='ordinary' explicitly for Matplotlib."
        )
    try:
        from waveforms import Waveform
        from waveforms_widgets.native_figure import (
            FigureIdentity,
            FigureRequest,
            produce_figure,
            reopen_figure,
        )

        return Waveform, FigureIdentity, FigureRequest, produce_figure, reopen_figure
    except (ImportError, SyntaxError) as exc:
        raise WaveformFigureError(
            "Install compatible Waveforms and Waveforms Widgets with native_figure export/reopen support "
            "in Python 3.12-3.13. No Matplotlib fallback is used; request backend='ordinary' explicitly."
        ) from exc


def waveform_figure(
    inputs: Sequence[Any],
    *,
    assets_dir: str | Path,
    request: Mapping[str, Any] | None = None,
    identities: Sequence[Mapping[str, str | None]] | None = None,
    read_disclosure: Mapping[str, Any] | None = None,
    caption: str | None = None,
    alt_text: str | None = None,
) -> Figure:
    """Prepare Waveforms (including families/ragged members) as managed art.

    ``request`` is exactly Widgets' FigureRequest, not an application session.
    Each caller identity can assert source/run/result/signal; absent identities
    stay null. The closed JSON evidence retains original selected samples and
    both representations, so extraction never needs the simulation sources.
    Digital semantics are refused by the delivered v1 producer, never erased.
    """
    _, Identity, Request, produce, reopen = _native()
    try:
        ids = (
            [dict(value) for value in identities]
            if identities is not None
            else [{} for _ in inputs]
        )
        if len(ids) != len(inputs) or any(
            set(v) - {"source", "run", "result", "signal"} for v in ids
        ):
            raise ValueError(
                "identities must correspond to inputs and use source/run/result/signal"
            )
        ids = [
            {key: value.get(key) for key in ("source", "run", "result", "signal")}
            for value in ids
        ]
        # Validate before rendering, not after an expensive successful export.
        if any(
            v is not None and (not isinstance(v, str) or not v)
            for row in ids
            for v in row.values()
        ):
            raise ValueError("identities must be nonempty strings or null")
        disclosure = dict(read_disclosure or {})
        json_bytes(disclosure)
        directory = Path(assets_dir).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".waveform-", dir=directory) as staging:
            artifact = produce(
                inputs,
                Path(staging) / "bundle",
                request=Request(**dict(request or {})),
                identities=[
                    Identity(**{k: v[k] for k in ("source", "result", "signal")})
                    for v in ids
                ],
            )
            payload, _ = reopen(artifact.manifest)
            members = {
                p.name: base64.b64encode(p.read_bytes()).decode("ascii")
                for p in artifact.manifest.parent.iterdir()
                if p.name != "manifest.json"
            }
            assets = {}
            for fmt, path in (("svg", artifact.svg), ("png", artifact.png)):
                content = path.read_bytes()
                final = directory / f"{digest(content)}.{fmt}"
                assets[fmt] = {"path": str(final), "sha256": digest(content)}
            origin = {
                "schema": SCHEMA,
                "producer_versions": {
                    name: importlib.metadata.version(name)
                    for name in ("presenter", "waveforms", "waveforms-widgets")
                },
                "identities": ids,
                "read_disclosure": {
                    "scope": "selected-original-members; upstream read extent unspecified; omitted members not fingerprinted",
                    "caller": disclosure,
                },
                "payload": payload,
                "members": members,
                "assets": assets,
                **{k: payload["request"][k] for k in ("width_in", "height_in", "dpi")},
            }
            origin["binding_digest"] = digest(json_bytes(origin))
            validate_origin(origin)
            # Materialize all returned paths before a Figure can be serialized.
            for fmt in ("svg", "png"):
                final = Path(assets[fmt]["path"])
                content = base64.b64decode(members[f"figure.{fmt}"])
                if final.exists() and (
                    final.is_symlink() or final.read_bytes() != content
                ):
                    raise ValueError(f"stale managed asset {final}; repair explicitly")
                if not final.exists():
                    try:
                        with final.open("xb") as stream:
                            stream.write(content)
                    except FileExistsError:
                        if final.is_symlink() or final.read_bytes() != content:
                            raise ValueError(f"managed asset collision at {final}")
        return Figure(
            svg=assets["svg"]["path"],
            png=assets["png"]["path"],
            width_in=origin["width_in"],
            caption=caption,
            alt_text=alt_text,
            waveform_origin=validate_origin(origin, check_files=True),
        )
    except WaveformFigureError:
        raise
    except Exception as exc:
        raise WaveformFigureError(
            f"Native waveform figure could not be prepared: {exc}. "
            "Correct the native request/dependencies, or explicitly request backend='ordinary'."
        ) from exc


def numeric_figure(traces, options: dict[str, Any]) -> Figure:
    """Translate the legacy numeric-builder vocabulary exactly once."""
    Waveform, _, _, _, _ = _native()
    options = dict(options)
    allowed = {
        "title",
        "x_label",
        "y_label",
        "x_unit",
        "y_unit",
        "x_log",
        "y_log",
        "line_style",
        "line_width",
        "line_styles",
        "colors",
        "x_lim",
        "y_lim",
        "figsize",
        "dpi",
        "caption",
        "width_in",
        "output_path",
        "vector",
        "format",
        "fallback_output_path",
        "alt_text",
        "assets_dir",
        "identities",
        "read_disclosure",
        "part",
        "interpolation",
        "members",
        "max_curves",
        "font_size_pt",
        "theme",
    }
    unsupported = set(options) - allowed
    if unsupported:
        raise WaveformFigureError(
            f"Native figures do not support {sorted(unsupported)}; "
            "omit those Matplotlib options or request backend='ordinary'."
        )
    from presenter.blocks.plot import format_axis_label

    def pick(value, index, label, default):
        if value is None:
            return default
        if isinstance(value, Mapping):
            return value.get(label, default)
        return value[index] if index < len(value) else default

    # Reuse ordinary color-name parsing, not its plotting/rendering machinery.
    from matplotlib.colors import to_hex, to_rgba

    colors = []
    widths = []
    inputs = []
    palette = ("#0072b2", "#d55e00", "#009e73", "#cc79a7")
    for i, trace in enumerate(traces):
        style = trace.line_style or pick(
            options.get("line_styles"), i, trace.label, options.get("line_style", "-")
        )
        if style != "-" or trace.marker is not None or trace.alpha is not None:
            raise WaveformFigureError(
                "Native v1 supports solid unmarked opaque traces only; request backend='ordinary' for other styling."
            )
        color = to_rgba(
            trace.color
            or pick(options.get("colors"), i, trace.label, palette[i % len(palette)])
        )
        if color[3] != 1:
            raise WaveformFigureError(
                "Native v1 requires opaque colors; request backend='ordinary' for transparency."
            )
        colors.append(to_hex(color))
        widths.append(
            trace.line_width
            if trace.line_width is not None
            else options.get("line_width", 1.5)
        )
        inputs.append(
            Waveform(
                np.asarray(trace.x),
                np.asarray(trace.y),
                xlabels=[options.get("x_label") or "x"],
                xunits=[options.get("x_unit") or ""],
                ylabel=trace.label or options.get("y_label") or "y",
                yunit=options.get("y_unit") or "",
                interp_mode=options.get("interpolation") or "linear",
            )
        )
    if len(set(widths)) != 1:
        raise WaveformFigureError(
            "Native v1 requires one shared line width; request backend='ordinary' for per-trace widths."
        )
    if options.get("format", "png") not in ("png", "svg", "both"):
        raise WaveformFigureError("Native figures support SVG and PNG only")
    if options.get("fallback_output_path") is not None:
        raise WaveformFigureError(
            "Native figures manage both references together; use assets_dir, not fallback_output_path"
        )
    size = options.get("figsize", (6.0, 4.0))
    width = size[0] if options.get("width_in") is None else options["width_in"]
    request = {
        "width_in": width,
        "height_in": size[1] * width / size[0],
        "dpi": options.get("dpi", 300),
        "title": options.get("title") or "",
        "xscale": "log" if options.get("x_log") else "linear",
        "yscale": "log" if options.get("y_log") else "linear",
        "colors": tuple(colors),
        "line_width_pt": widths[0],
    }
    for source, dest in (
        ("x_lim", "xlim"),
        ("y_lim", "ylim"),
        ("part", "part"),
        ("interpolation", "interpolation"),
        ("members", "members"),
        ("max_curves", "max_curves"),
        ("font_size_pt", "font_size_pt"),
        ("theme", "theme"),
    ):
        if source in options:
            request[dest] = options[source]
    for axis in ("x", "y"):
        label = format_axis_label(
            options.get(f"{axis}_label"), options.get(f"{axis}_unit")
        )
        if label:
            request[f"{axis}label"] = label
    directory = options.get("assets_dir")
    if directory is None:
        output = options.get("output_path")
        directory = (
            Path(str(output) + ".assets")
            if output is not None
            else tempfile.mkdtemp(prefix="presenter_waveform_")
        )
    elif options.get("output_path") is not None:
        raise WaveformFigureError("Choose assets_dir or output_path, not both")
    return waveform_figure(
        inputs,
        assets_dir=directory,
        request=request,
        identities=options.get("identities"),
        read_disclosure=options.get("read_disclosure"),
        caption=options.get("caption"),
        alt_text=options.get("alt_text"),
    )
