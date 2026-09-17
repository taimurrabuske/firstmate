"""Native defaults, portable scientific evidence and explicit ordinary opt-in."""

from __future__ import annotations

import base64
import builtins
import copy
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from presenter.blocks import (
    PlotTrace,
    build_plot,
    build_plot_from_arrays,
    build_plot_from_csv,
    build_waveform_plot,
    waveform_figure,
)
from presenter.core import DocumentBuilder, DocumentSpec
from presenter.core.blocks import ImageBlock, PlotBlock, validate_block
from presenter.core.errors import WaveformFigureError
from presenter.waveform_origin import (
    digest,
    extract_waveform_bundle,
    json_bytes,
    safe_svg,
    validate_origin,
)


@pytest.fixture(scope="module")
def native():
    if not (3, 12) <= sys.version_info[:2] < (3, 14):
        pytest.skip("native producer requires Python 3.12-3.13")
    pytest.importorskip("waveforms_widgets.native_figure")
    from waveforms import Waveform
    from waveforms_widgets.native_figure import reopen_figure

    return Waveform, reopen_figure


@pytest.fixture
def figure(native, tmp_path):
    return build_plot(
        x=np.arange(7.0),
        y=[0.0, 1.0, np.nan, np.inf, -np.inf, 0.0, 1.0],
        x_label="Time",
        x_unit="s",
        y_label="Output",
        y_unit="V",
        title="Native signal",
        assets_dir=tmp_path / "assets",
        dpi=96,
        figsize=(4, 3),
        as_figure=True,
        identities=[
            {
                "source": "simulation",
                "run": "run-42",
                "result": "tran",
                "signal": "vout",
            }
        ],
        read_disclosure={"warnings": ["caller-supplied disclosure"]},
    )


def test_ordinary_imports_do_not_import_qt_or_native():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
import presenter, presenter.blocks, presenter.waveform_origin
assert not any(n.startswith(('PySide6', 'PyQt', 'waveforms')) for n in sys.modules)
from presenter.blocks import build_plot
b = build_plot(x=[0,1], y=[0,1], backend='ordinary')
assert 'waveform_origin' not in b
assert not any(n.startswith(('PySide6', 'PyQt', 'waveforms')) for n in sys.modules)
""",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_missing_dependency_never_falls_back(monkeypatch, tmp_path):
    original = builtins.__import__

    def missing(name, *args, **kwargs):
        if name.startswith("waveforms"):
            raise ImportError("not installed")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    with pytest.raises(WaveformFigureError, match="Python 3.12|Install compatible"):
        build_plot(x=[0, 1], y=[0, 1], assets_dir=tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "builder,arguments",
    [
        (build_plot, {"x": [0, 1, 2], "y": [0, 1, 0]}),
        (
            build_waveform_plot,
            {"traces": [PlotTrace([0, 1, 2], [0, 1, 0], label="signal")]},
        ),
        (build_plot, {"traces": [{"x": [0, 1, 2], "y": [0, 1, 0], "label": "mapped"}]}),
        (
            build_plot_from_arrays,
            {"x": [0, 1, 2], "y": {"a": [0, 1, 0], "b": [1, 0, 1]}},
        ),
        (build_plot_from_arrays, {"x": [0, 1, 2], "y": [[0, 1, 0], [1, 0, 1]]}),
        (build_plot_from_csv, {"csv_source": "time,voltage\n0,0\n1,1\n2,0\n"}),
    ],
)
def test_every_numeric_entry_defaults_native(native, tmp_path, builder, arguments):
    block = builder(**arguments, assets_dir=tmp_path, dpi=96)
    assert block["type"] == "plot" and "circuit_origin" not in block
    evidence = validate_origin(block["waveform_origin"], block, check_files=True)
    assert evidence["payload"]["schema"] == "waveforms-widgets.native-figure/v1"
    assert Image.open(block["png"]).size == (576, 384)
    assert all(v is None for v in evidence["identities"][0].values())


def test_detached_json_typed_and_spec_roundtrip(figure, native, tmp_path):
    block = figure.to_block("plot")
    assert "circuit_origin" not in block
    assert (
        PlotBlock.from_dict(block).to_dict()["waveform_origin"]
        == figure.waveform_origin
    )
    assert ImageBlock.from_figure(figure).waveform_origin == figure.waveform_origin
    spec = DocumentBuilder("waveform").slide("native").add(figure).build()
    loaded = DocumentSpec.from_json(spec.to_json())
    origin = loaded.to_dict()["slides"][0]["blocks"][0]["waveform_origin"]
    assert origin == figure.to_dict()["waveform_origin"]
    manifest = extract_waveform_bundle(origin, tmp_path / "reopened")
    payload, members = native[1](manifest)
    assert payload["selected"][0]["y"]["nonfinite"] == {
        "nan": 1,
        "positive_infinity": 1,
        "negative_infinity": 1,
    }
    assert origin["identities"][0]["run"] == "run-42"
    assert members[0].xunits == ["s"] and members[0].yunit == "V"
    np.testing.assert_equal(members[0].y, [0, 1, np.nan, np.inf, -np.inf, 0, 1])
    origin["identities"][0]["run"] = "changed"
    assert figure.waveform_origin["identities"][0]["run"] == "run-42"


@pytest.mark.parametrize("part", ["real", "imag", "mag", "phase", "db20"])
def test_complex_original_components_and_log(native, tmp_path, part):
    x = np.logspace(0, 2, 30)
    y = np.linspace(1, 3, 30) + 1j * np.linspace(3, 1, 30)
    fig = build_plot(
        x=x,
        y=y,
        part=part,
        x_log=True,
        assets_dir=tmp_path / "art",
        dpi=96,
        as_figure=True,
    )
    payload, members = native[1](
        extract_waveform_bundle(fig.waveform_origin, tmp_path / "bundle")
    )
    np.testing.assert_array_equal(members[0].y, y)
    assert payload["request"]["part"] == part
    assert payload["selected"][0]["y"]["dtype"] == y.dtype.str


@pytest.mark.parametrize("ragged", [False, True])
def test_families_selection_member_axes_and_cap(native, tmp_path, ragged):
    Waveform, reopen = native
    if ragged:
        x = np.empty(3, dtype=object)
        y = np.empty(3, dtype=object)
        for i in range(3):
            x[i] = np.linspace(0, i + 1, i + 4)
            y[i] = np.sin(x[i])
    else:
        x = np.arange(5.0)
        y = np.array([x, x + 1, x + 2])
    wf = Waveform(
        [np.array([10.0, 20.0, 30.0]), x],
        y,
        xlabels=["corner", "time"],
        xunits=["", "s"],
        ylabel="family",
    )
    fig = waveform_figure(
        [wf],
        assets_dir=tmp_path / "assets",
        request={"members": ((2, 0, 1),), "max_curves": 2, "dpi": 96},
    )
    payload, members = reopen(
        extract_waveform_bundle(fig.waveform_origin, tmp_path / "bundle")
    )
    assert payload["inputs"][0]["selected"] == [2, 0]
    assert payload["inputs"][0]["omitted"] == [1]
    for actual, index in zip(members, [2, 0]):
        np.testing.assert_equal(actual.get_x(0), x[index] if ragged else x)
        np.testing.assert_equal(actual.y, y[index])
    assert [r["coordinates"] for r in payload["selected"]] == [[2], [0]]


def test_step_geometry_and_endpoint_ink(native, tmp_path):
    fig = build_plot(
        x=np.arange(5.0),
        y=[0, 0, 1, 1, 0],
        interpolation="step",
        assets_dir=tmp_path,
        x_lim=(0.0, 4.0),
        y_lim=(-0.2, 1.2),
        dpi=144,
        as_figure=True,
    )
    payload = fig.waveform_origin["payload"]
    assert payload["selected"][0]["interpolation"] == "step"
    assert payload["geometry"][0]["x_extent"] == [0.0, 4.0]
    image = np.array(Image.open(fig.png).convert("RGB"))
    blue = (image[:, :, 2].astype(int) - image[:, :, 0] > 50) & (image[:, :, 1] > 60)
    ys, xs = np.where(blue)
    assert len(xs) > 400 and xs.max() - xs.min() > image.shape[1] * 0.7
    assert ys.max() - ys.min() > image.shape[0] * 0.3
    # Signal reaches both plot endpoints; its terminal step is not silently lost.
    assert np.count_nonzero(blue[:, xs.max() - 2 : xs.max() + 1]) > 5


@pytest.mark.parametrize(
    "options",
    [
        {"grid": False},
        {"legend": False},
        {"line_style": "--"},
        {"x_lim": (None, 1)},
        {"colors": ["invalid-color"]},
        {"backend": "auto"},
    ],
)
def test_unsupported_options_are_actionable(native, tmp_path, options):
    with pytest.raises(WaveformFigureError, match="ordinary|backend|Native"):
        build_plot(x=[0, 1, 2], y=[0, 1, 0], assets_dir=tmp_path, **options)


@pytest.mark.parametrize(
    "semantics",
    [
        {"signed": True},
        {"bus_width": 8},
        {"display_hint": "digital"},
        {"xmask": np.array([0, 1, 0, 0])},
        {"zmask": np.array([0, 1, 0, 0])},
        {"wmask": np.array([0, 1, 0, 0])},
    ],
)
def test_digital_semantics_are_not_erased(native, tmp_path, semantics):
    wf = native[0](np.arange(4.0), np.array([0, 1, 1, 0]), **semantics)
    with pytest.raises(WaveformFigureError, match="digital"):
        waveform_figure([wf], assets_dir=tmp_path)


@pytest.mark.parametrize("key", ["source", "svg", "png", "fallback", "width_in"])
def test_wrong_refs_and_size(figure, key):
    block = figure.to_block("plot")
    block[key] = 2 if key == "width_in" else "wrong-reference"
    with pytest.raises(WaveformFigureError):
        validate_block(block)


@pytest.mark.parametrize(
    "mutation", ["schema", "member", "missing", "binding", "request"]
)
def test_mutated_closed_evidence(figure, mutation):
    origin = copy.deepcopy(figure.waveform_origin)
    if mutation == "schema":
        origin["schema"] = "future/v2"
    elif mutation == "member":
        origin["members"]["0-y.npy"] = base64.b64encode(b"changed").decode()
    elif mutation == "missing":
        del origin["members"]["0-y.npy"]
    elif mutation == "request":
        origin["payload"]["request"]["part"] = "imag"
    if mutation != "binding":
        origin["binding_digest"] = digest(
            json_bytes({k: v for k, v in origin.items() if k != "binding_digest"})
        )
    else:
        origin["binding_digest"] = "bad"
    with pytest.raises(WaveformFigureError):
        validate_origin(origin)


@pytest.mark.parametrize(
    "fragment",
    [
        '<use href="https://example.com/a.svg#b"/>',
        "<script/>",
        '<style>@import "https://example.com/x";</style>',
        '<path fill="url(file:///tmp/private)"/>',
        '<image href="file:///tmp/private"/>',
    ],
)
def test_unsafe_svg_rejected(fragment):
    with pytest.raises(ValueError, match="unsafe"):
        safe_svg(f'<svg xmlns="http://www.w3.org/2000/svg">{fragment}</svg>'.encode())


@pytest.mark.parametrize("action", ["mutate", "remove"])
def test_missing_or_mutated_asset_before_dispatch(
    figure, tmp_path, monkeypatch, action
):
    import importlib

    engine = importlib.import_module("presenter.core.render")
    monkeypatch.setattr(engine, "_engines", dict(engine._engines))
    monkeypatch.setattr(engine, "_stubs", set(engine._stubs))
    path = Path(figure.png)
    if action == "remove":
        path.unlink()
    else:
        path.write_bytes(b"changed")
    called = []
    engine.register_engine("docx", lambda *a: called.append(True), replace=True)
    with pytest.raises(WaveformFigureError):
        engine.render(
            DocumentBuilder("bad").slide("bad").add(figure).build(),
            {"format": "docx", "template": "unused"},
            tmp_path / "bad.docx",
        )
    assert not called


def _rebind(origin):
    payload = origin["payload"]
    payload["evidence_sha256"] = digest(
        json_bytes({k: v for k, v in payload.items() if k != "evidence_sha256"})
    )
    origin["binding_digest"] = digest(
        json_bytes({k: v for k, v in origin.items() if k != "binding_digest"})
    )


@pytest.mark.parametrize(
    "mutation",
    ["external_svg", "unknown_field", "traversal", "pickle", "cap", "future_schema"],
)
def test_rehashed_untrusted_payload_is_still_rejected(figure, mutation):
    import io
    import xml.etree.ElementTree as ET

    origin = copy.deepcopy(figure.waveform_origin)
    if mutation == "external_svg":
        root = ET.fromstring(base64.b64decode(origin["members"]["figure.svg"]))
        ET.SubElement(
            root,
            "{http://www.w3.org/2000/svg}use",
            {"href": "https://example.com/private.svg"},
        )
        content = ET.tostring(root)
        record = origin["payload"]["representations"]["svg"]
        record.update(sha256=digest(content), bytes=len(content))
        origin["members"]["figure.svg"] = base64.b64encode(content).decode()
        origin["assets"]["svg"]["sha256"] = digest(content)
    elif mutation == "pickle":
        stream = io.BytesIO()
        np.save(
            stream, np.array([{"untrusted": True}], dtype=object), allow_pickle=True
        )
        content = stream.getvalue()
        origin["members"]["0-y.npy"] = base64.b64encode(content).decode()
        origin["payload"]["selected"][0]["y"].update(
            sha256=digest(content), bytes=len(content), dtype="|O", shape=[1]
        )
    elif mutation == "unknown_field":
        origin["payload"]["selected"][0]["hidden"] = "not closed"
    elif mutation == "traversal":
        origin["payload"]["selected"][0]["y"]["file"] = "../private.npy"
    elif mutation == "cap":
        origin["payload"]["inputs"][0]["available"] = 10**12
    else:
        origin["payload"]["schema"] = "waveforms-widgets.native-figure/v2"
    _rebind(origin)
    with pytest.raises(WaveformFigureError):
        validate_origin(origin)


def test_named_colors_limits_and_managed_legacy_output(native, tmp_path):
    block = build_plot(
        x=[0, 1, 2],
        y={"A": [0, 1, 0]},
        colors={"A": "red"},
        x_lim=(0, 2),
        y_lim=(-1, 2),
        width_in=4,
        figsize=(6, 4),
        output_path=tmp_path / "plot.svg",
        dpi=96,
    )
    origin = block["waveform_origin"]
    assert Path(block["source"]).parent == tmp_path / "plot.svg.assets"
    assert origin["payload"]["request"]["colors"] == ["#ff0000"]
    assert origin["height_in"] == pytest.approx(8 / 3)
    assert origin["payload"]["geometry"][0]["x_window"] == [0, 2]


def test_native_default_typography_units_and_contrast(figure):
    import xml.etree.ElementTree as ET

    root = ET.parse(figure.svg)
    texts = {
        node.text.strip(): node
        for node in root.iter()
        if node.tag.endswith("}text") and node.text
    }
    for expected in ("Native signal", "Time [s]", "Output [V]"):
        node = texts[expected]
        assert float(node.attrib["font-size"]) == round(10 * 96 / 72)
        assert node.attrib["font-family"]
        rgb = np.array(
            [int(node.attrib["fill"][i : i + 2], 16) / 255 for i in (1, 3, 5)]
        )
        linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
        luminance = float(linear @ np.array([0.2126, 0.7152, 0.0722]))
        assert 1.05 / (luminance + 0.05) > 7  # high contrast on the native light page


def test_direct_engine_rejects_bad_bound_asset_before_opening_template(
    figure, tmp_path
):
    from presenter.render_docx.engine import render as docx_render
    from presenter.render_pptx.engine import render as pptx_render

    Path(figure.svg).unlink()
    for engine, fmt in ((docx_render, "docx"), (pptx_render, "pptx")):
        with pytest.raises(WaveformFigureError):
            engine(
                [figure.to_block()],
                {"format": fmt, "template": "nonexistent"},
                tmp_path / f"bad.{fmt}",
            )
