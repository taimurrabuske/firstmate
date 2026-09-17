# presenter

`presenter` is a Python library for template-driven PowerPoint (`.pptx`) and Word (`.docx`) authoring.
It assembles a document from plain JSON-serializable content blocks, binds it to a corporate template through a TemplateBinding, and renders it through a format-specific engine.
Its target content is technical: schematics, waveform plots, symbolic equations, and PVT or specification tables.

This file is the library's documentation of record.
The block contract and the TemplateBinding contract below are the canonical text that every part of the library codes against.

## Layout

- `presenter/core/` - the foundation: the specification model (`spec.py`), block validation and typed accessors (`blocks.py`), the render entry point and engine registry (`render.py`), and the error hierarchy (`errors.py`).
- `presenter/templates/` - corporate template ingestion and master binding; produces TemplateBinding files.
- `presenter/render_docx/` - the DOCX datasheet render engine.
- `presenter/render_pptx/` - the PPTX deck render engine.
- `presenter/omml/` - LaTeX -> MathML -> OMML conversion pipeline and Office Math element builders.
- `presenter/blocks/` and `presenter/artifacts.py` - technical content block generators and the artifact source that image and plot blocks reference.
- `presenter/layouts/` - convenience functions building common design-review slide layouts from those blocks.

Every package above is landed and composes into one working pipeline.
`examples/datasheet_demo.py` is the runnable, end-to-end version of the shape below: it binds a fixture `.docx` template, assembles a spec from every block type including a table, a plot, and an equation, and renders a real `.docx` file.

## Install

```sh
pip install -e ".[dev]"
python -m pytest
```

Python 3.10 or newer is required.
Runtime dependencies are `python-pptx`, `python-docx`, `matplotlib`, `sympy`, and `pillow`; `pytest` is the only development extra.
The pytest configuration in `pyproject.toml` points at `tests/presenter`, so a bare `python -m pytest` from the repository root runs the library's suite and nothing else.

## SVG rasterization

SVG rasterization is optional for ordinary images and only needed when an `image` or `plot` block carries an `svg` without an explicit `fallback` PNG.
Preparing a native circuit figure also requires rasterization, as described below.
Supplying an explicit `fallback` bypasses rasterization entirely and needs no renderer at all.
When automatic rasterization is needed, `presenter._ooxml.rasterize` looks for one of four supported renderers, in this order: the `cairosvg` Python package, then the `rsvg-convert`, `inkscape`, or ImageMagick `convert` command-line tools.
`presenter._ooxml.rasterize.is_rasterizer_available()` and `available_rasterizers()` report what is detected at runtime, and rasterization raises `MissingRendererError` with install guidance when none is found.

Install one of the following to enable it:

```sh
# cairosvg, a pip package (needs the system cairo library most Linux distros
# already ship; see https://cairosvg.org/documentation/ for other platforms).
pip install -e ".[svg]"

# Or a system command-line renderer, any one of:
sudo apt-get install librsvg2-bin   # rsvg-convert, Debian/Ubuntu
brew install librsvg                # rsvg-convert, macOS
sudo apt-get install inkscape       # inkscape
sudo apt-get install imagemagick    # convert
```

CI installs `rsvg-convert` explicitly for the same reason a project pins any other tool version: reproducible coverage that does not depend on what a runner image happens to ship with.
`tests/presenter/ooxml/test_rasterize.py` covers dispatch and error handling without needing a renderer; `tests/presenter/ooxml/test_rasterize_renderer.py` exercises a real installed renderer and is marked `svg_renderer`, skipping locally when none is installed.

## Circuit-native figures

Use `presenter.blocks.circuit_figure` for technical circuit content.
Its only implicit producer is Schematic's closed circuit-figure exporter, also used by Canvas; it never infers a circuit from a caption, parses a raw netlist, consults a live Canvas session, or substitutes generic art.
Canvas canonical capture chooses Razavi symbols and resolves native hierarchy/connectivity before export; explicit Schematic input preserves its authored symbols and geometry rather than re-symbolizing it.
Install a Schematic build providing `schematic.core.circuit_figure.export_circuit_figure` and `reopen_circuit_figure` with its dependencies, plus CairoSVG (`.[svg]`), librsvg, or Inkscape.
Canvas itself is only required when producing a Canvas artifact, not when Presenter consumes one.

```python
from pathlib import Path
from presenter.blocks import circuit_figure
from presenter.core import DocumentBuilder

# Consume the closed SVG returned by Canvas export_circuit_figure().
figure = circuit_figure(Path("resolved-circuit.svg"), assets_dir="assets/circuits")
spec = DocumentBuilder("Design report").slide("Circuit").add(figure).build()

# Alternatively use an explicit SchematicData or schematic-document envelope.
# Supply a SymbolLibrary or its closed SVG definitions, never an ambient palette.
figure = circuit_figure(
    schematic_document, symbols=symbol_library, assets_dir="assets/circuits",
    width_in=4.0, request={"children": child_envelopes, "selected_path": ["Xstage"]},
    caption="Selected stage",
)
```

The helper prepares a `Figure` once, materializing content-addressed SVG and PNG files in `assets_dir`, then follows the existing image/block, DocumentBuilder, core render, and Office engine flow.
Keep that managed directory with saved JSON specifications; the JSON contains asset paths and digests, never binary image bytes.
The default raster density is 300 pixels/inch at the requested physical width, using 96-DPI SVG unit conversion so font sizes do not grow with raster density.
An already-resolved artifact fixes its own width; to change it, re-export with the producer at the new size rather than overriding the bound width or images.
Ordinary explicit `Figure`, `image`, and `plot` behavior is unchanged.

Circuit blocks carry a separate `circuit_origin` v1 object, owned by `presenter.circuit_origin`.
It retains the input source envelope (including its metadata/revision), the producer's complete closed payload, symbol definitions, child documents, selected occurrence, connectivity, annotation and analytical records, physical size, and both asset bindings.
SHA-256 digests cover source, symbols, selected occurrence, hierarchy, annotations, analyses, producer payload, SVG, and PNG.
These detect changed content, not author authenticity.
Figure conversion, typed ImageBlock/PlotBlock access, and SlideSpec/DocumentSpec JSON round trips preserve the object; core rendering checks the actual asset bytes before engine dispatch.
Missing dependencies, symbols, children, invalid occurrences, unsupported annotation content, and stale or mismatched representations raise `PresenterError` subclasses with a concrete diagnostic instead of drawing replacement art.

PPTX retains SVG plus PNG visual relationships; DOCX displays PNG.
Both saved Office packages additionally retain JSON evidence and exact SVG/PNG source parts under `presenter/`, reachable via the `urn:presenter:relationships:circuit-origin` relationship.
Each manifest entry identifies the flattened engine-input block index and its `package_parts` retrieval addresses; the original local paths remain audit data, not external package dependencies.
Extract these related parts to retrieve evidence without the original asset directory.
Third-party Office editing/resaving may strip custom parts, so verify retention after such processing.

`tests/presenter/integrate/test_circuit_figures.py` exercises native selection, evidence round trips, invalid bindings, both Office packages, and Canvas-produced RC/two-level hierarchy artifacts.
Native tests require the producer packages and skip explicitly when absent; run `python -m pytest tests/presenter` with those packages installed to validate the complete integration.

## Core API

Everything below is importable from `presenter.core`.

- `DocumentSpec` and `SlideSpec` are dataclasses describing one deliverable.
  A `SlideSpec` is one slide in a deck and one section in a document; each holds an ordered list of block dicts.
  Both round-trip to plain dicts through `to_dict()` and `from_dict()`, and `DocumentSpec` also offers `to_json()` and `from_json()`.
- `DocumentBuilder` assembles a `DocumentSpec` fluently: `DocumentBuilder(title).slide("Overview").add(block).build()`.
  Every `add` validates immediately, so an invalid block fails where it is added.
- `validate_block(block)` returns the normalized form of one block dict and raises `BlockValidationError` otherwise.
  `validate_blocks(blocks)` does the same for a list, labelling each error with its index.
  The typed accessors (`TextBlock`, `TableBlock`, `ImageBlock`, `PlotBlock`, `EquationBlock`, `TocBlock`, `PageBreakBlock`) offer attribute access through `from_dict()` and `to_dict()`, and `block_from_dict()` picks the right one.
  Builder helpers `text()`, `table()`, `image()`, `plot()`, `equation()`, `toc()`, and `pagebreak()` in `presenter.core.blocks` return validated dicts.
- `render(spec, binding, output_path)` dispatches on `binding["format"]` to the registered engine and returns the written path.
  The output path must end in the binding's format extension.
- `register_engine(fmt, engine)` plugs an engine into the registry; `unregister_engine`, `get_engine`, `registered_formats`, and `is_engine_implemented` inspect and manage it.
  The `pptx` and `docx` slots exist from import time with stubs that raise `EngineNotImplementedError` (a subclass of both `RenderError` and `NotImplementedError`) until a real engine registers.
  Registration is explicit and opt-in, never a side effect of importing a package: call `presenter.render_docx.register()` once (an application entry point, a test fixture, or `examples/datasheet_demo.py`) before the first `render()` call targeting `docx`.
- `PresenterError` is the base of every library error; `SpecError`, `BlockValidationError`, `BindingError`, `RenderError`, `UnknownFormatError`, and `EngineNotImplementedError` refine it.

### Engine contract

An engine is a plain callable `engine(document, binding, output_path) -> output_path`.
`document` is the normalized dict from `DocumentSpec.to_dict()`, `binding` is the TemplateBinding dict with `format` lower-cased, and `output_path` is a `pathlib.Path`.
The engine writes the file and returns the path it wrote.
Engines code against these plain dicts, not against `presenter.core` dataclasses, so each lane integrates without importing the others.
`presenter.render_docx.render` predates this contract and takes a flat block list rather than a full document dict; `presenter.render_docx.render_document` is the adapter matching this Engine shape, flattening a document's slides (each slide's title becomes a `heading1` block ahead of its own blocks) before calling `render`.
`presenter.render_docx.register()` registers that adapter.

## Block contract

Shared block contract (plain JSON-serializable dicts):

- `{"type": "text", "style": "body|heading1|heading2|caption", "text": str}`
- `{"type": "table", "caption": str|null, "headers": [str, ...], "rows": [[value, ...], ...], "style": "grid|plain|striped"}`
- `{"type": "image", "source": "<artifact ref or filesystem path>", "width_in": float|null, "caption": str|null, "fallback": str|null, "svg": str|null, "alt_text": str|null}`
- `{"type": "plot", "source": "<artifact ref to a rendered plot image>", "width_in": float|null, "caption": str|null, "fallback": str|null, "svg": str|null, "alt_text": str|null}`
- `{"type": "equation", "latex": str, "font_size_pt": float|null, "image": str|null, "mode": "native|native-preferred|native-required|image|monospace"|null}`
- `{"type": "toc"}` and `{"type": "pagebreak"}`

Validation rules layered on that contract by `presenter.core.blocks`:

- `style` defaults to `body` for text and `grid` for tables when omitted or `null`; every other optional field normalizes to `null` the same way, so an explicit `null` is always equivalent to omitting the field.
- A table's rows must each have exactly as many values as there are headers, and a value is a string, number, boolean, or `null`; both engines render a `null` cell as empty text rather than the literal string `"None"`.
- A table's optional `alignments` is a list of `"left"|"center"|"right"`, one per header column, when given; both engines apply it to header and body cells alike.
- `width_in` and `font_size_pt` must be positive numbers when given.
- `source` and `latex` must be non-empty strings.
- An equation's optional `image` names a pre-rendered picture (a filesystem path or artifact reference, resolved the same way as an `image`/`plot` block's `source`) to insert in place of the raw LaTeX string; `presenter.blocks.equation` populates it.
- An equation's optional `mode` selects native Office Math rendering (`"native"`, `"native-preferred"`, or `"native-required"`) or image/monospace fallback (`"image"`, `"monospace"`).
  In native mode, DOCX emits `m:oMath` / `m:oMathPara` elements and PPTX emits DrawingML text math containers (`a14:m` / `CT_TextMath`).
  Native-preferred mode explicitly falls back to high-resolution image rendering when native math conversion encounters unsupported complex macros.
- An `image` or `plot` block can carry an SVG vector image (via `svg` or an `.svg` `source`) alongside a raster `fallback` PNG.
  In PowerPoint (`.pptx`), this uses dual-relationship packaging (`asvg:svgBlip` referencing pure vector SVG alongside the PNG fallback) for razor-sharp vector zooming with full backwards compatibility.
  When only an SVG is provided, a high-resolution PNG fallback is cleanly rasterized automatically; see "SVG rasterization" below for the renderer this requires.
- An image or plot can carry `circuit_origin`, the separately validated object described in "Circuit-native figures"; `png` is also accepted as the `fallback` alias.
- Keys outside the contract are rejected, so a misspelled field fails validation instead of being ignored.

## Markdown input

`presenter.markdown` converts rich-text Markdown into content blocks in one call.
`markdown_to_blocks(text)` parses a GFM subset - ATX headings, pipe tables with column alignments, bullet and numbered lists, fenced code, images, block quotes, thematic breaks (as page breaks), and plain paragraphs - and returns validated blocks per the contract above; `markdown_file(path)` reads a file first and delegates.
The parser is pure standard library; the supported subset and its limitations are documented in the `presenter.markdown` module docstring.

## TemplateBinding contract

Shared TemplateBinding contract (JSON file, schema owned by the template lane):

```json
{"format": "pptx"|"docx", "template": "<path>", "name": str, "layouts": {...}, "placeholders": {...}, "styles": {...}}
```

`presenter.core.render.validate_binding` checks only the top-level shape it dispatches on: `format` must name a registered format, `template` must be a non-empty path string, `name` a string when present, and `layouts`, `placeholders`, and `styles` mappings when present.
The meaning of those mappings belongs to `presenter/templates/`.

## Layout convenience functions

`presenter.layouts` builds common design-review slides in one call instead of
hand-placed blocks: `title_bullets`, `title_single_image`,
`split_half_text_images`, `two_column_bullets`, `bullets_and_table`, and
`image_grid`.

Library principle: prefer native PowerPoint features and layouts over reinventing what the format already provides.
Each helper chooses a named native layout; `presenter/layouts/slides.py` owns the per-helper placement contract and the unimplemented image-grid limitation.

Every helper returns a plain dict accepted by `SlideSpec.from_dict` without stripping any fields.
`placeholder_roles` maps region labels to lists of zero-based block indices; indices must be in range and assigned at most once.
The optional `columns` hint is a positive integer retained for image grids, not a request for grid placement in either renderer.
Both fields survive document JSON serialization and core normalization.
The slide's `title` is never repeated in its blocks or region mapping.
DOCX ignores layout hints and stacks the flat block list in reading order.

PPTX tables use one shared region budget for placement and pagination, including native TABLE placeholders and occupied body regions.
Captions travel with the first table chunk; continuation slides repeat headers, column widths, alignment, and the continued title, not the caption.
A header or indivisible row that exceeds an empty region's estimated height raises `ValueError` instead of being placed off-slide.
Row-height estimates use explicit cell line counts, not a general text-fitting or layout solver.
Saved-output regressions live in `tests/presenter/render_pptx/test_render_regions.py`.

## End-to-end example

This example shows the intended shape now that the template, DOCX, and content-block lanes have landed; `examples/datasheet_demo.py` is its runnable counterpart, generating its own fixture template and artifacts at runtime.
`render` dispatches to whichever engine is registered for `binding["format"]`, so register the DOCX adapter once before the final call.

```python
import json

import presenter.render_docx
from presenter.core import DocumentBuilder, render
from presenter.core.blocks import equation, image, pagebreak, plot, table, text, toc

presenter.render_docx.register()  # plug the DOCX engine into presenter.core.render

# Produced by the template lane from a corporate .dotx or .potx file.
with open("bindings/acme-datasheet.json") as fh:
    binding = json.load(fh)  # {"format": "docx", "template": "templates/acme.dotx", ...}

spec = (
    DocumentBuilder("ACME LDO-3V3 Datasheet", author="Analog IC team")
    .slide("Contents").add(toc())
    .slide("Overview")
    .add(text("A 3.3 V, 500 mA low-dropout regulator.", style="body"))
    .add(image("artifact://schematics/ldo-top", width_in=5.0, caption="Top-level schematic"))
    .slide("Electrical characteristics")
    .add(table(
        ["Parameter", "Min", "Typ", "Max", "Unit"],
        [["Output voltage", 3.234, 3.3, 3.366, "V"], ["Dropout", None, 150, 250, "mV"]],
        caption="Over PVT unless noted",
        style="striped",
    ))
    .add(equation(r"V_{out} = V_{ref} \left(1 + \frac{R_1}{R_2}\right)", font_size_pt=12))
    .add(pagebreak())
    .slide("Transient response")
    .add(plot("artifact://plots/load-step", width_in=6.0, caption="Load step 10 mA to 500 mA"))
    .build()
)

render(spec, binding, "out/ldo-3v3-datasheet.docx")
```
