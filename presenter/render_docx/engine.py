"""Render presenter content blocks into a .docx datasheet or report.

The engine takes plain JSON-serializable block dicts (the shared presenter
block contract) and an optional TemplateBinding dict (schema owned by
``presenter.templates``), and writes a .docx file via python-docx.

Block types handled:

- ``text``: paragraph with the logical style (``body`` | ``heading1`` |
  ``heading2`` | ``caption``). Logical names are resolved through
  ``binding["styles"]`` when present, then canonical built-in names, then
  ``Normal``.
- ``table``: header row (bold) plus data rows; ``style`` maps ``grid`` to
  ``Table Grid``, ``striped`` to ``Light Shading Accent 1``, and ``plain``
  to no explicit style. A ``null`` cell renders as empty text. The optional
  ``alignments`` list applies ``left``/``center``/``right`` paragraph
  alignment per column to both header and body cells. The caption paragraph
  is placed above the table.
- ``image`` / ``plot``: picture inserted from the block ``source`` (a
  filesystem path, or an artifact reference looked up in
  ``binding["artifacts"]`` when the literal path does not exist), honoring
  ``width_in``. The caption paragraph is placed below the picture.
- ``equation``: when the block carries an ``image`` key, that pre-rendered
  picture is inserted; otherwise the ``latex`` string falls back to a
  styled monospace run sized by ``font_size_pt``.
- ``toc``: a native Word TOC field.
- ``pagebreak``: a native page break.

No other presenter subpackage is imported: blocks and binding arrive as
plain dicts. ``render`` returns a plain summary dict.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from docx import Document
from docx.document import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

from presenter._ooxml import is_svg_asset, rasterize_svg_to_png
from presenter.blocks.equation import render_latex_to_png
from presenter.omml import (
    EquationConversionError,
    convert_latex_to_docx_element,
    omml_to_docx_element,
)

__all__ = ["render"]

Block = Mapping[str, Any]
Binding = Mapping[str, Any]

#: Logical text-style name -> canonical python-docx style name.
_DEFAULT_TEXT_STYLES: dict[str, str] = {
    "body": "Normal",
    "heading1": "Heading 1",
    "heading2": "Heading 2",
    "caption": "Caption",
}

#: Table-style keyword -> canonical python-docx table style (None: leave default).
_DEFAULT_TABLE_STYLES: dict[str, str | None] = {
    "grid": "Table Grid",
    "striped": "Light Shading Accent 1",
    "plain": None,
}

#: Cell alignment name -> python-docx WD_ALIGN_PARAGRAPH enum.
_ALIGN_MAP: dict[str, WD_ALIGN_PARAGRAPH] = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
}

_TOC_FIELD_INSTRUCTION = 'TOC \\o "1-3" \\h \\z \\u'

_Handler = Callable[[DocxDocument, Block, Binding, Mapping[str, Any]], None]


def render(
    blocks: Sequence[Block],
    binding: Binding | None,
    output_path: str | Path,
) -> dict[str, Any]:
    """Render ``blocks`` into a .docx file at ``output_path``.

    When ``binding["template"]`` names an existing .docx file, the document
    starts from that template (its content and styles are preserved and the
    blocks are appended); when ``template`` is empty or absent, a blank
    document is used. A template path that does not exist raises (python-docx
    ``PackageNotFoundError``) rather than silently falling back to a blank
    document. A ``binding`` whose ``format`` is present and is not
    ``"docx"`` is rejected.

    Returns a plain JSON-serializable summary dict with ``format``,
    ``output_path``, ``template`` (path or None), and ``blocks_rendered``.
    """
    resolved_binding: Binding = binding or {}
    fmt = resolved_binding.get("format")
    if fmt is not None and fmt != "docx":
        raise ValueError(f"docx renderer requires binding format 'docx', got {fmt!r}")
    template = resolved_binding.get("template")
    if template:
        document = Document(str(template))
    else:
        document = Document()
    styles: Mapping[str, Any] = resolved_binding.get("styles") or {}

    rendered = 0
    for block in blocks:
        _render_block(document, block, resolved_binding, styles)
        rendered += 1

    output = Path(output_path)
    if output.parent and str(output.parent):
        output.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(output))
    return {
        "format": "docx",
        "output_path": str(output),
        "template": str(template) if template else None,
        "blocks_rendered": rendered,
    }


def _render_block(
    document: DocxDocument,
    block: Block,
    binding: Binding,
    styles: Mapping[str, Any],
) -> None:
    block_type = block.get("type")
    handler = _HANDLERS.get(block_type)  # type: ignore[arg-type]
    if handler is None:
        raise ValueError(f"unsupported block type: {block_type!r}")
    handler(document, block, binding, styles)


def _style_candidates(logical: str, styles: Mapping[str, Any]) -> list[str]:
    """Ordered paragraph-style candidates for a logical style name."""
    candidates = [
        styles.get(logical),
        _DEFAULT_TEXT_STYLES.get(logical),
        logical,
        "Normal",
    ]
    seen: set[str] = set()
    ordered: list[str] = []
    for name in candidates:
        if isinstance(name, str) and name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _set_paragraph_style(paragraph: Any, candidates: Sequence[str]) -> bool:
    """Apply the first candidate style the document actually defines."""
    for name in candidates:
        try:
            paragraph.style = name
            return True
        except KeyError:
            continue
    return False


def _add_caption(
    document: DocxDocument,
    text: str,
    styles: Mapping[str, Any],
) -> None:
    paragraph = document.add_paragraph()
    _set_paragraph_style(paragraph, _style_candidates("caption", styles))
    paragraph.add_run(str(text))


def _add_text(
    document: DocxDocument,
    block: Block,
    binding: Binding,
    styles: Mapping[str, Any],
) -> None:
    logical = str(block.get("style") or "body")
    paragraph = document.add_paragraph()
    _set_paragraph_style(paragraph, _style_candidates(logical, styles))
    paragraph.add_run(str(block.get("text") or ""))


def _add_table(
    document: DocxDocument,
    block: Block,
    binding: Binding,
    styles: Mapping[str, Any],
) -> None:
    headers = [str(header) for header in (block.get("headers") or [])]
    rows = [
        ["" if value is None else str(value) for value in row]
        for row in (block.get("rows") or [])
    ]
    if headers:
        for row_index, row in enumerate(rows):
            if len(row) > len(headers):
                raise ValueError(
                    f"table row {row_index} has {len(row)} cells, more than "
                    f"the {len(headers)} header columns"
                )
    caption = block.get("caption")
    if caption:
        _add_caption(document, str(caption), styles)

    ncols = len(headers) if headers else max((len(row) for row in rows), default=0)
    nrows = (1 if headers else 0) + len(rows)
    if ncols == 0 or nrows == 0:
        return

    table = document.add_table(rows=nrows, cols=ncols)
    table_style = _DEFAULT_TABLE_STYLES.get(
        str(block.get("style") or "grid"), "Table Grid"
    )
    if table_style is not None:
        try:
            table.style = table_style
        except KeyError:
            pass

    alignments = block.get("alignments")
    first_data_row = 0
    if headers:
        for col, header in enumerate(headers):
            paragraph = table.cell(0, col).paragraphs[0]
            run = paragraph.add_run(header)
            run.bold = True
            _apply_column_alignment(paragraph, alignments, col)
        first_data_row = 1

    for row_index, row in enumerate(rows):
        for col in range(ncols):
            value = row[col] if col < len(row) else ""
            cell = table.cell(first_data_row + row_index, col)
            cell.text = value
            _apply_column_alignment(cell.paragraphs[0], alignments, col)


def _apply_column_alignment(paragraph: Any, alignments: Any, col: int) -> None:
    """Apply the alignment named for ``col`` in ``alignments``, if any."""
    if not alignments or col >= len(alignments):
        return
    alignment = _ALIGN_MAP.get(str(alignments[col]).lower().strip())
    if alignment is not None:
        paragraph.alignment = alignment


def _resolve_picture_source(source: str, binding: Binding) -> Path:
    """Resolve a picture source to an existing file.

    A literal filesystem path wins; otherwise the source is treated as an
    artifact reference looked up in ``binding["artifacts"]`` (the
    forward-compatible hook for the artifact source lane).
    """
    path = Path(source)
    if path.is_file():
        return path
    artifacts = binding.get("artifacts") or {}
    if isinstance(artifacts, Mapping):
        mapped = artifacts.get(source)
        if isinstance(mapped, (str, Path)):
            mapped_path = Path(mapped)
            if mapped_path.is_file():
                return mapped_path
            raise FileNotFoundError(
                f"picture source {source!r} maps to {str(mapped_path)!r} in "
                "binding['artifacts'] but that file does not exist"
            )
    raise FileNotFoundError(
        f"picture source not found on disk and not mapped in binding['artifacts']: {source!r}"
    )


def _add_picture_run(paragraph: Any, source: Path, width_in: float | None) -> None:
    run = paragraph.add_run()
    run.add_picture(
        str(source), width=Inches(width_in) if width_in is not None else None
    )


def _add_picture_block(
    document: DocxDocument,
    block: Block,
    binding: Binding,
    styles: Mapping[str, Any],
) -> None:
    source = block.get("source")
    svg = block.get("svg")
    fallback = block.get("fallback") or block.get("png")
    if not source and not svg and not fallback:
        raise ValueError(f"{block.get('type')!r} block requires a 'source' key")
    target_src = str(fallback or source or svg)
    if svg:
        resolved_svg = _resolve_picture_source(str(svg), binding)
        if fallback:
            resolved = _resolve_picture_source(str(fallback), binding)
        else:
            resolved = rasterize_svg_to_png(resolved_svg, dpi=300)
    else:
        resolved = _resolve_picture_source(target_src, binding)
        if is_svg_asset(resolved):
            if fallback:
                resolved = _resolve_picture_source(str(fallback), binding)
            else:
                resolved = rasterize_svg_to_png(resolved, dpi=300)
    paragraph = document.add_paragraph()
    _add_picture_run(paragraph, resolved, block.get("width_in"))
    caption = block.get("caption")
    if caption:
        _add_caption(document, str(caption), styles)


def _add_equation(
    document: DocxDocument,
    block: Block,
    binding: Binding,
    styles: Mapping[str, Any],
) -> None:
    mode = block.get("mode") or binding.get("equation_mode")
    image = block.get("image")
    latex = str(block.get("latex") or "")
    omml_raw = block.get("omml")
    caption = block.get("caption")

    if mode is None:
        if image:
            mode = "image"
        else:
            mode = "monospace"

    if mode in ("native", "native-preferred", "native-required"):
        try:
            if omml_raw:
                omml_elem = omml_to_docx_element(str(omml_raw), display=True)
            else:
                omml_elem = convert_latex_to_docx_element(latex, display=True)
            paragraph = document.add_paragraph()
            paragraph._p.append(omml_elem)
            if caption:
                _add_caption(document, str(caption), styles)
            return
        except (EquationConversionError, Exception):
            if mode == "native-required":
                raise
            # Fall back to high-resolution image rendering
            fallback_img = image
            if not fallback_img and latex:
                try:
                    font_size_pt = block.get("font_size_pt")
                    size = float(font_size_pt) if font_size_pt is not None else 14.0
                    fallback_img = str(render_latex_to_png(latex, font_size_pt=size))
                except (ValueError, RuntimeError, OSError):
                    fallback_img = None
            if fallback_img:
                resolved = _resolve_picture_source(str(fallback_img), binding)
                if is_svg_asset(resolved):
                    fallback = block.get("fallback") or block.get("png")
                    if fallback:
                        resolved = _resolve_picture_source(str(fallback), binding)
                    else:
                        resolved = rasterize_svg_to_png(resolved, dpi=300)
                paragraph = document.add_paragraph()
                _add_picture_run(paragraph, resolved, None)
                if caption:
                    _add_caption(document, str(caption), styles)
                return

    if mode == "image" or image:
        img_src = image
        if not img_src and latex:
            font_size_pt = block.get("font_size_pt")
            size = float(font_size_pt) if font_size_pt is not None else 14.0
            img_src = str(render_latex_to_png(latex, font_size_pt=size))
        resolved = _resolve_picture_source(str(img_src), binding)
        if is_svg_asset(resolved):
            fallback = block.get("fallback") or block.get("png")
            if fallback:
                resolved = _resolve_picture_source(str(fallback), binding)
            else:
                resolved = rasterize_svg_to_png(resolved, dpi=300)
        paragraph = document.add_paragraph()
        _add_picture_run(paragraph, resolved, None)
        if caption:
            _add_caption(document, str(caption), styles)
        return

    paragraph = document.add_paragraph()
    run = paragraph.add_run(latex)
    run.font.name = "Courier New"
    font_size_pt = block.get("font_size_pt")
    if font_size_pt is not None:
        run.font.size = Pt(float(font_size_pt))
    if caption:
        _add_caption(document, str(caption), styles)


def _add_toc(
    document: DocxDocument,
    block: Block,
    binding: Binding,
    styles: Mapping[str, Any],
) -> None:
    paragraph = document.add_paragraph()
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = _TOC_FIELD_INSTRUCTION
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    placeholder = OxmlElement("w:t")
    placeholder.text = "Table of contents (update fields to populate)"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for element in (begin, instruction, separate, placeholder, end):
        run._r.append(element)


def _add_pagebreak(
    document: DocxDocument,
    block: Block,
    binding: Binding,
    styles: Mapping[str, Any],
) -> None:
    paragraph = document.add_paragraph()
    paragraph.add_run().add_break(WD_BREAK.PAGE)


_HANDLERS: dict[str, _Handler] = {
    "text": _add_text,
    "table": _add_table,
    "image": _add_picture_block,
    "plot": _add_picture_block,
    "equation": _add_equation,
    "toc": _add_toc,
    "pagebreak": _add_pagebreak,
}
