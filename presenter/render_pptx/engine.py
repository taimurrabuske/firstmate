"""Render presenter content blocks into a .pptx slide deck.

The engine takes plain JSON-serializable block dicts (the shared presenter
block contract) and an optional TemplateBinding dict (schema owned by
``presenter.templates``), and writes a .pptx file via python-pptx.

Block types handled:

- ``text``: a paragraph with the logical style (``body`` | ``heading1`` |
  ``heading2`` | ``caption``). ``heading1`` fills the slide's ``title``
  placeholder, ``body`` fills the slide's ``body`` placeholder (appending a
  paragraph when the block is not the first), and ``heading2``/``caption``
  become text boxes. Placeholder candidates are resolved through
  ``binding["layouts"]`` (layout name -> placeholder name -> role) first and
  the placeholder's own type second, mirroring the role vocabulary of
  ``presenter.templates.pptx``.
- ``table``: header row (bold) plus data rows as a table. ``style`` maps
  ``grid`` to a bold first row with no banding, ``striped`` to a bold first
  row with horizontal banding, and ``plain`` to neither. A ``table``-role
  placeholder is used when present; otherwise a table shape is placed in the
  content flow. The caption paragraph is placed above the table. Large tables
  that exceed the slide vertical budget automatically split across continuation
  slides, repeating table headers, preserving column widths and alignments,
  and appending ``(continued)`` to the slide title.
- ``image`` / ``plot``: picture inserted from the block ``source`` (a
  filesystem path, or an artifact reference looked up in
  ``binding["artifacts"]`` when the literal path does not exist), honoring
  ``width_in``. Without ``width_in`` a ``picture``-role placeholder is used
  when present. The caption paragraph is placed below the picture.
- ``equation``: when the block carries an ``image`` key, that pre-rendered
  picture is inserted; otherwise the ``latex`` string falls back to a
  monospace text box sized by ``font_size_pt``.
- ``toc``: a section-divider slide. On a slide that already carries content
  it starts a new divider slide; on an untouched slide it stays there.
- ``pagebreak``: a new slide.

Slide flow starts on one new slide and continues across slides as the
``toc`` and ``pagebreak`` blocks direct; free shapes (text boxes, tables,
pictures) stack downward in the content flow of the current slide.

Slides use the first layout, searched master by master, that offers a
``body``-role placeholder; the theme fonts from ``binding["styles"]`` size
free text boxes. A binding that names a template file starts from it (its
existing slides are preserved and content is appended); an empty or absent
``template`` starts from a default presentation. A template path that does
not exist raises (python-pptx ``PackageNotFoundError``) rather than
silently falling back.

No other presenter subpackage is imported: blocks and binding arrive as
plain dicts. ``render`` returns a plain summary dict; ``render_document``
implements the ``presenter.core.render`` engine contract and returns the
written path.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

from presenter._ooxml import (
    RELATIONSHIP_TYPE_IMAGE,
    attach_svg_blip_extension,
    ensure_svg_content_type,
    get_or_add_svg_part,
    is_svg_asset,
    rasterize_svg_to_png,
)
from presenter.blocks.equation import render_latex_to_png
from presenter.omml import (
    EquationConversionError,
    convert_latex_to_pptx_element,
    omml_to_pptx_element,
)

__all__ = ["render", "render_document"]

Block = Mapping[str, Any]
Binding = Mapping[str, Any]

#: EMU per point and per inch, for geometry arithmetic.
_EMU_PER_INCH = 914400

#: Slide margin and vertical gap for shapes placed in the content flow.
_MARGIN = Inches(0.5)
_GAP = Inches(0.2)
_MIN_TABLE_ROW_HEIGHT = Inches(0.4)

#: Logical text-style name -> point size for free text boxes.
_TEXT_BOX_FONT_PT = {"heading1": 28.0, "heading2": 20.0, "body": 18.0, "caption": 12.0}

#: Table-style keyword -> (bold first row, horizontal banding).
_TABLE_BANDING = {
    "grid": (True, False),
    "striped": (True, True),
    "plain": (False, False),
}

#: Cell alignment name -> python-pptx PP_ALIGN enum.
_ALIGN_MAP = {
    "left": PP_ALIGN.LEFT,
    "center": PP_ALIGN.CENTER,
    "right": PP_ALIGN.RIGHT,
}

# Placeholder-type names -> render-engine-facing role. Mirrors the role
# vocabulary of presenter.templates.pptx so both lanes agree on what a
# binding's "layouts" mapping can name; defined locally because engines do
# not import sibling subpackages.
_ROLE_BY_PLACEHOLDER_TYPE = {
    "TITLE": "title",
    "CENTER_TITLE": "title",
    "SUBTITLE": "subtitle",
    "BODY": "body",
    "OBJECT": "body",
    "PICTURE": "picture",
    "TABLE": "table",
    "CHART": "chart",
    "DATE": "date",
    "FOOTER": "footer",
    "SLIDE_NUMBER": "slide_number",
    "HEADER": "header",
}

_Handler = Callable[["DeckWriter", Block], None]


def render(
    blocks: Sequence[Block],
    binding: Binding | None,
    output_path: str | Path,
) -> dict[str, Any]:
    """Render ``blocks`` into a .pptx deck at ``output_path``.

    Returns a plain JSON-serializable summary dict with ``format``,
    ``output_path``, ``template`` (path or None), and ``blocks_rendered``.
    """
    writer, template = _open_deck(binding)
    writer.new_slide()
    rendered = 0
    for block in blocks:
        writer.render_block(block)
        rendered += 1
    from presenter._ooxml.circuit import retain_circuit_evidence

    retain_circuit_evidence(writer.presentation.part, blocks, fmt="pptx")
    output = _save(writer.presentation, output_path)
    return {
        "format": "pptx",
        "output_path": str(output),
        "template": str(template) if template else None,
        "blocks_rendered": rendered,
    }


def render_document(
    document: Mapping[str, Any],
    binding: Binding | None,
    output_path: str | Path,
) -> Path:
    """Render a normalized ``DocumentSpec`` dict as a deck.

    This is the engine callable registered into ``presenter.core.render``.
    Each entry of ``document["slides"]`` starts one slide (tables may add
    continuation slides): its
    ``title`` fills the slide's title placeholder, its ``layout`` names the
    slide layout (an unknown name raises), its ``notes`` becomes the slide's
    speaker notes, and its ``blocks`` render onto the slide through the same
    block handlers as :func:`render`.
    """
    writer, _template = _open_deck(binding)
    for slide_spec in document.get("slides") or []:
        writer.new_slide(
            layout_name=slide_spec.get("layout"), title=slide_spec.get("title")
        )
        notes = slide_spec.get("notes")
        if notes:
            writer.set_notes(notes)
        roles = slide_spec.get("placeholder_roles") or {}
        blocks = slide_spec.get("blocks") or []
        writer.configure_regions(roles, blocks)
        block_roles = {index: role for role, indices in roles.items() for index in indices}
        order = list(range(len(blocks)))
        if set(block_roles.values()) <= {"left", "right"} and len(block_roles) == len(blocks):
            # Populate the static peer before a table can create continuations,
            # even when that table is the left (first in reading order) region.
            table_regions = {block_roles[i] for i in order if blocks[i].get("type") == "table"}
            order.sort(key=lambda i: block_roles[i] in table_regions)
        for index in order:
            writer.render_block(blocks[index], region=block_roles.get(index))
    from presenter._ooxml.circuit import retain_circuit_evidence

    retain_circuit_evidence(writer.presentation.part,
                            (block for slide in document.get("slides", []) for block in slide.get("blocks", [])),
                            fmt="pptx")
    return _save(writer.presentation, output_path)


def _open_deck(binding: Binding | None) -> tuple[DeckWriter, str | None]:
    ensure_svg_content_type()
    resolved: Binding = binding or {}
    fmt = resolved.get("format")
    if fmt is not None and fmt != "pptx":
        raise ValueError(f"pptx renderer requires binding format 'pptx', got {fmt!r}")
    template = resolved.get("template")
    if template:
        prs = Presentation(str(template))
    else:
        prs = Presentation()
    return DeckWriter(prs, resolved), template


def _save(prs: Presentation, output_path: str | Path) -> Path:
    output = Path(output_path)
    if output.parent and str(output.parent):
        output.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(output))
    return output


def _estimate_box_height(text: str, width: int, font_pt: float) -> int:
    """Rough wrapped-height estimate (EMU) for a text box of ``width``."""
    chars_per_line = max(8, int(width / _EMU_PER_INCH * 72 / (font_pt * 0.5)))
    lines = max(1, math.ceil(len(text) / chars_per_line))
    return int(lines * font_pt * 1.4 * 12700) + _EMU_PER_INCH // 10


def _estimate_table_row_height(row: Sequence[Any]) -> int:
    """Estimate row height (EMU) for a table row based on cell line counts."""
    max_lines = 1
    for cell in row:
        lines = str(cell).count("\n") + 1
        max_lines = max(max_lines, lines)
    if max_lines <= 1:
        return int(_MIN_TABLE_ROW_HEIGHT)
    return max(int(_MIN_TABLE_ROW_HEIGHT), int(max_lines * Pt(14) * 1.4) + int(Pt(8)))


class DeckWriter:
    """Slide-flow writer shared by :func:`render` and :func:`render_document`."""

    def __init__(self, prs: Presentation, binding: Binding) -> None:
        self._prs = prs
        self._binding = binding
        styles = binding.get("styles")
        theme = styles.get("theme") if isinstance(styles, Mapping) else None
        fonts = theme.get("fonts") if isinstance(theme, Mapping) else None
        self._theme_fonts: Mapping[str, Any] = (
            fonts if isinstance(fonts, Mapping) else {}
        )
        self._layout_roles: Mapping[str, Any] = binding.get("layouts") or {}
        self._slide: Any = None
        self._slide_has_content = False
        self._used_placeholder_idxs: set[int] = set()
        self._cursor: int = int(_MARGIN)
        self._current_layout_name: str | None = None
        self._current_title: str | None = None
        self._text_placeholder_idxs: set[int] = set()
        self._regions: dict[str, int] = {}
        self._region_headings: dict[str, int] = {}
        self._region_cursors: dict[str, int] = {}
        self._active_region: str | None = None
        self._flow_cursor = self._cursor
        self._region_picture_remaining: dict[str, int] = {}

    @property
    def presentation(self) -> Presentation:
        return self._prs

    # -- slide flow ---------------------------------------------------------

    def new_slide(
        self, layout_name: str | None = None, title: str | None = None
    ) -> None:
        """Start a new slide, optionally on a named layout with a title."""
        self._current_layout_name = layout_name
        self._current_title = title
        layout = self._resolve_layout(layout_name)
        self._slide = self._prs.slides.add_slide(layout)
        self._slide_has_content = False
        self._used_placeholder_idxs = set()
        self._text_placeholder_idxs = set()
        self._regions = {}
        self._region_headings = {}
        self._region_cursors = {}
        self._region_picture_remaining = {}
        self._active_region = None
        self._cursor = int(_MARGIN)
        if title:
            placeholder = self._take_placeholder("title")
            if placeholder is not None:
                placeholder.text = str(title)
                self._advance_past(placeholder)
        self._flow_cursor = self._cursor

    def configure_regions(
        self, roles: Mapping[str, Any], blocks: Sequence[Block] = ()
    ) -> None:
        """Bind left/right helper regions to peer native content placeholders.

        Grid hints remain metadata only. Named non-peer roles retain the
        ordinary block-driven behavior. No arbitrary placement solver is used.
        """
        if not ({"left", "right"} & roles.keys()):
            return
        if blocks:
            self._region_picture_remaining = {
                role: sum(blocks[i].get("type") in ("image", "plot") for i in indices)
                for role, indices in roles.items()
            }
        layout = self._slide.slide_layout
        candidates = [
            ph for ph in self._slide.placeholders
            if self._placeholder_role(layout, ph) in ("body", "left", "right")
        ]
        # Comparison has BODY headings above OBJECT content placeholders.
        objects = [ph for ph in candidates if ph.placeholder_format.type.name == "OBJECT"]
        peers = objects if len(objects) == 2 else candidates
        if len(peers) != 2:
            raise ValueError("left/right regions require two native content placeholders")
        peers.sort(key=lambda ph: (ph.left, ph.top))
        if peers[0].left + peers[0].width > peers[1].left:
            raise ValueError("left/right regions require non-overlapping peer placeholders")
        for role, ph in zip(("left", "right"), peers):
            self._regions[role] = ph.placeholder_format.idx
            self._region_cursors[role] = int(ph.top)
            headings = [
                h for h in candidates if h not in peers
                and h.left == ph.left and h.top + h.height <= ph.top
            ]
            if headings:
                self._region_headings[role] = headings[0].placeholder_format.idx

    def _region_placeholder(self) -> Any:
        if self._active_region is None:
            return None
        return self._slide.placeholders[self._regions[self._active_region]]

    def _select_region(self, region: str | None) -> None:
        if self._active_region is not None:
            self._region_cursors[self._active_region] = self._cursor
        else:
            self._flow_cursor = self._cursor
        self._active_region = region if region in self._regions else None
        self._cursor = (
            self._region_cursors[self._active_region]
            if self._active_region is not None else self._flow_cursor
        )

    def _continue_slide(self) -> None:
        region = self._active_region
        roles = dict(self._regions)
        self.new_slide(self._current_layout_name, self._continuation_title())
        self.configure_regions(roles)
        self._select_region(region)

    def set_notes(self, notes: str) -> None:
        """Set the current slide's speaker notes."""
        self._slide.notes_slide.notes_text_frame.text = str(notes)

    def render_block(self, block: Block, region: str | None = None) -> None:
        self._select_region(region)
        block_type = block.get("type")
        handler = _HANDLERS.get(block_type)  # type: ignore[arg-type]
        if handler is None:
            raise ValueError(f"unsupported block type: {block_type!r}")
        handler(self, block)

    def _iter_layouts(self) -> Any:
        for master in self._prs.slide_masters:
            yield from master.slide_layouts

    def _resolve_layout(self, layout_name: str | None) -> Any:
        if layout_name:
            for layout in self._iter_layouts():
                if layout.name == layout_name:
                    return layout
            raise ValueError(f"template has no slide layout named {layout_name!r}")
        for layout in self._iter_layouts():
            if any(
                self._placeholder_role(layout, ph) == "body"
                for ph in layout.placeholders
            ):
                return layout
        return next(self._iter_layouts())

    def _placeholder_role(self, layout: Any, placeholder: Any) -> str:
        roles = self._layout_roles.get(layout.name)
        if isinstance(roles, Mapping):
            role = roles.get(placeholder.name)
            if isinstance(role, str) and role:
                return role
        placeholder_type = placeholder.placeholder_format.type
        type_name = placeholder_type.name if placeholder_type is not None else ""
        return _ROLE_BY_PLACEHOLDER_TYPE.get(type_name, type_name.lower())

    def _take_placeholder(self, role: str) -> Any:
        """Claim the first unused placeholder with ``role`` for one fill."""
        placeholder = self._peek_placeholder(role)
        if placeholder is not None:
            self._used_placeholder_idxs.add(placeholder.placeholder_format.idx)
        return placeholder

    def _peek_placeholder(self, role: str) -> Any:
        """Return the first unused placeholder with ``role`` without claiming it."""
        layout = self._slide.slide_layout
        for placeholder in self._slide.placeholders:
            idx = placeholder.placeholder_format.idx
            if idx in self._used_placeholder_idxs:
                continue
            if role != "title" and self._active_region is not None:
                if idx != self._regions[self._active_region]:
                    continue
            elif idx in self._regions.values():
                continue
            if self._placeholder_role(layout, placeholder) == role:
                return placeholder
        return None

    def _continuation_title(self) -> str:
        """Return the slide title annotated with (continued) for table continuation."""
        if self._current_title:
            base = self._current_title.strip()
            if not base.endswith("(continued)"):
                return f"{base} (continued)"
            return base
        return "(continued)"

    def _table_slot(self) -> tuple[Any, int, int, int, int]:
        """One geometry source for both table budgeting and placement."""
        target = self._region_placeholder()
        if target is None:
            target = self._peek_placeholder("table")
        if target is None:
            target = self._peek_placeholder("body")
        bottom = self._content_bottom()
        if target is not None:
            return (target, int(target.left), max(self._cursor, int(target.top)),
                    int(target.width), min(bottom, int(target.top + target.height)))
        return None, self._content_left(), self._cursor, self._content_width(), bottom

    def _available_table_height(self) -> int:
        _ph, _left, top, _width, bottom = self._table_slot()
        return max(0, bottom - top)

    # -- text ---------------------------------------------------------------

    def _add_text(self, block: Block) -> None:
        style = str(block.get("style") or "body")
        text = str(block.get("text") or "")
        if style == "heading1":
            self._current_title = text
            placeholder = self._take_placeholder("title")
            if placeholder is not None:
                # A title fill does not count as slide content, so a slide
                # titled before a toc block stays that slide's divider.
                placeholder.text = text
                self._advance_past(placeholder)
                return
        elif style == "heading2" and self._active_region in self._region_headings:
            placeholder = self._slide.placeholders[self._region_headings[self._active_region]]
            placeholder.text = text
            self._used_placeholder_idxs.add(placeholder.placeholder_format.idx)
            self._slide_has_content = True
            return
        elif style == "body":
            placeholder = self._region_placeholder()
            if placeholder is None:
                placeholder = next((
                    ph for ph in self._slide.placeholders
                    if self._placeholder_role(self._slide.slide_layout, ph) == "body"
                    and (ph.placeholder_format.idx not in self._used_placeholder_idxs
                         or ph.placeholder_format.idx in self._text_placeholder_idxs)
                ), None)
            if placeholder is not None:
                idx = placeholder.placeholder_format.idx
                if idx in self._text_placeholder_idxs or (
                    idx not in self._used_placeholder_idxs
                    and (self._cursor <= placeholder.top or not self._slide_has_content)
                ):
                    self._append_body_text(placeholder, text)
                    self._used_placeholder_idxs.add(idx)
                    self._text_placeholder_idxs.add(idx)
                    self._advance_past(placeholder)
                    self._slide_has_content = True
                    return
        self._add_text_box(text, style)
        self._slide_has_content = True

    @staticmethod
    def _append_body_text(placeholder: Any, text: str) -> None:
        frame = placeholder.text_frame
        if frame.text:
            frame.add_paragraph().text = text
        else:
            frame.text = text

    def _add_text_box(self, text: str, style: str) -> None:
        font_pt = _TEXT_BOX_FONT_PT.get(style, 18.0)
        width = self._content_width()
        height = _estimate_box_height(text, width, font_pt)
        if style == "body" and self._cursor + height > self._content_bottom():
            if not self._slide_has_content:
                raise ValueError("body text cannot fit in an empty slide content region")
            self._continue_slide()
            self._add_text({"type": "text", "style": style, "text": text})
            return
        box = self._slide.shapes.add_textbox(
            self._content_left(), self._cursor, width, height
        )
        frame = box.text_frame
        frame.word_wrap = True
        frame.text = text
        self._style_text_box_run(frame, style, font_pt)
        self._cursor += int(box.height) + int(_GAP)

    def _style_text_box_run(self, frame: Any, style: str, font_pt: float) -> None:
        runs = frame.paragraphs[0].runs
        if not runs:
            return
        font = runs[0].font
        font.size = Pt(font_pt)
        font.bold = style in ("heading1", "heading2")
        font.italic = style == "caption"
        font_role = "major" if style in ("heading1", "heading2") else "minor"
        typeface = self._theme_fonts.get(font_role)
        if isinstance(typeface, str) and typeface:
            font.name = typeface

    def _add_caption_box(
        self, text: str, width: int | None = None, left: int | None = None
    ) -> None:
        box_width = int(width) if width else self._content_width()
        box = self._slide.shapes.add_textbox(
            self._content_left() if left is None else left,
            self._cursor,
            box_width,
            _estimate_box_height(text, box_width, 12.0),
        )
        frame = box.text_frame
        frame.word_wrap = True
        frame.text = text
        self._style_text_box_run(frame, "caption", 12.0)
        self._cursor += int(box.height) + int(_GAP)

    # -- table ---------------------------------------------------------------

    def _add_table(self, block: Block) -> None:
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
        ncols = len(headers) if headers else max((len(row) for row in rows), default=0)
        if ncols == 0 and not caption:
            return

        style = str(block.get("style") or "grid")
        alignments = block.get("alignments")
        header_height = _estimate_table_row_height(headers) if headers else 0

        # Keep the caption with the first chunk, including when the table
        # must move off a slide whose body region already belongs to text.
        min_needed = header_height + (_estimate_table_row_height(rows[0]) if rows and ncols else 0)
        for attempt in range(2):
            _ph, left, top, width, bottom = self._table_slot()
            caption_height = (
                _estimate_box_height(str(caption), width, 12.0) + int(_GAP)
                if caption else 0
            )
            if min_needed + caption_height <= bottom - top:
                break
            if attempt == 0 and self._slide_has_content:
                self._continue_slide()
            else:
                raise ValueError("table header/row and caption cannot fit in an empty slide content region")
        self._cursor = top
        if caption:
            self._add_caption_box(str(caption), width=width, left=left)
            self._slide_has_content = True
        if ncols == 0:
            return

        remaining_rows = list(rows)
        first_chunk = True
        captured_col_widths: list[int] | None = None

        while remaining_rows or first_chunk:
            available_height = self._available_table_height()
            accumulated_h = header_height
            count = 0
            chunk_row_heights: list[int] = []
            if headers:
                chunk_row_heights.append(header_height)

            for r in remaining_rows:
                r_h = _estimate_table_row_height(r)
                if accumulated_h + r_h > available_height:
                    break
                accumulated_h += r_h
                chunk_row_heights.append(r_h)
                count += 1

            if accumulated_h > available_height or (remaining_rows and count == 0):
                raise ValueError("table header/row cannot fit in an empty slide content region")

            chunk = remaining_rows[:count]
            remaining_rows = remaining_rows[count:]

            nrows = (1 if headers else 0) + len(chunk)
            table, anchor = self._place_table(nrows, ncols, chunk_row_heights)

            first_row, banding = _TABLE_BANDING.get(style, (True, False))
            table.first_row = first_row
            table.horz_banding = banding

            # Capture or preserve identical column widths
            if captured_col_widths is None:
                captured_col_widths = [col.width for col in table.columns]
            else:
                for col_idx, width in enumerate(captured_col_widths):
                    table.columns[col_idx].width = width

            first_data_row = 0
            if headers:
                for col, header in enumerate(headers):
                    cell = table.cell(0, col)
                    cell.text = header
                    for p in cell.text_frame.paragraphs:
                        for run in p.runs:
                            run.font.bold = True
                        if alignments and col < len(alignments):
                            align_key = str(alignments[col]).lower().strip()
                            if align_key in _ALIGN_MAP:
                                p.alignment = _ALIGN_MAP[align_key]
                first_data_row = 1

            for row_index, row_data in enumerate(chunk):
                for col in range(ncols):
                    cell = table.cell(first_data_row + row_index, col)
                    cell.text = row_data[col] if col < len(row_data) else ""
                    if alignments and col < len(alignments):
                        align_key = str(alignments[col]).lower().strip()
                        if align_key in _ALIGN_MAP:
                            for p in cell.text_frame.paragraphs:
                                p.alignment = _ALIGN_MAP[align_key]

            self._slide_has_content = True
            self._advance_past(anchor)
            first_chunk = False

            if remaining_rows:
                self._continue_slide()

    def _place_table(
        self, nrows: int, ncols: int, row_heights: Sequence[int] | None = None
    ) -> tuple[Any, Any]:
        placeholder, left, top, width, bottom = self._table_slot()
        total_height = sum(row_heights) if row_heights else int(_MIN_TABLE_ROW_HEIGHT) * nrows
        if top + total_height > bottom:
            raise ValueError("table exceeds its content region")
        if placeholder is not None:
            self._used_placeholder_idxs.add(placeholder.placeholder_format.idx)
        if placeholder is not None and hasattr(placeholder, "insert_table"):
            # insert_table returns a replacement GraphicFrame, not a Table;
            # the original placeholder is invalid after the insertion.
            frame = placeholder.insert_table(nrows, ncols)
            frame.left, frame.top, frame.width = left, top, width
        else:
            frame = self._slide.shapes.add_table(nrows, ncols, left, top, width, total_height)
        table = frame.table
        if row_heights:
            for r_idx, r_h in enumerate(row_heights):
                if r_idx < len(table.rows):
                    table.rows[r_idx].height = r_h
        return table, frame

    # -- pictures ------------------------------------------------------------

    def _add_picture_block(self, block: Block) -> None:
        source = block.get("source")
        svg = block.get("svg")
        fallback = block.get("fallback") or block.get("png")
        if not source and not svg and not fallback:
            raise ValueError(f"{block.get('type')!r} block requires a 'source' key")

        # Determine whether this is an SVG picture
        is_svg = False
        resolved_svg: Path | None = None
        if svg:
            resolved_svg = _resolve_picture_source(str(svg), self._binding)
            is_svg = True
        elif source:
            resolved = _resolve_picture_source(str(source), self._binding)
            if is_svg_asset(resolved):
                resolved_svg = resolved
                is_svg = True
            else:
                resolved_svg = None

        if is_svg and resolved_svg is not None:
            # SVG mode: resolve or cleanly rasterize PNG fallback
            if fallback:
                resolved_png = _resolve_picture_source(str(fallback), self._binding)
            else:
                resolved_png = rasterize_svg_to_png(resolved_svg, dpi=300)

            svg_bytes = resolved_svg.read_bytes()
            width_in = block.get("width_in")
            width = Emu(int(Inches(float(width_in)))) if width_in is not None else None

            if width is None:
                placeholder = self._take_placeholder("picture")
                if placeholder is not None and hasattr(placeholder, "insert_picture"):
                    picture = placeholder.insert_picture(str(resolved_png))
                    svg_part = get_or_add_svg_part(self._prs.part.package, svg_bytes)
                    svg_rId = self._slide.part.relate_to(svg_part, RELATIONSHIP_TYPE_IMAGE)
                    attach_svg_blip_extension(picture._element.blipFill.blip, svg_rId)
                    self._finish_picture(picture, block)
                    return

            picture = self._slide.shapes.add_picture(
                str(resolved_png), _MARGIN, self._cursor, width=width
            )
            content_width = self._content_width()
            if picture.width > content_width:
                scale = content_width / picture.width
                picture.width = int(picture.width * scale)
                picture.height = int(picture.height * scale)

            svg_part = get_or_add_svg_part(self._prs.part.package, svg_bytes)
            svg_rId = self._slide.part.relate_to(svg_part, RELATIONSHIP_TYPE_IMAGE)
            attach_svg_blip_extension(picture._element.blipFill.blip, svg_rId)
            self._finish_picture(picture, block)
            return

        # Ordinary raster picture
        resolved = _resolve_picture_source(str(source), self._binding)
        width_in = block.get("width_in")
        width = Emu(int(Inches(float(width_in)))) if width_in is not None else None
        if width is None:
            placeholder = self._take_placeholder("picture")
            if placeholder is not None and hasattr(placeholder, "insert_picture"):
                picture = placeholder.insert_picture(str(resolved))
                self._finish_picture(picture, block)
                return
        picture = self._slide.shapes.add_picture(
            str(resolved), _MARGIN, self._cursor, width=width
        )
        content_width = self._content_width()
        if picture.width > content_width:
            scale = content_width / picture.width
            picture.width = int(picture.width * scale)
            picture.height = int(picture.height * scale)
        self._finish_picture(picture, block)

    def _finish_picture(self, picture: Any, block: Block) -> None:
        region = self._region_placeholder()
        if region is not None:
            # Peer-region pictures fit inside their native content slot. Multiple
            # images share its remaining height; this is not image-grid layout.
            remaining = max(1, self._region_picture_remaining.get(self._active_region, 1))
            available = (self._content_bottom() - self._cursor) // remaining
            caption = block.get("caption")
            caption_height = (
                _estimate_box_height(str(caption), int(region.width), 12.0) + int(_GAP)
                if caption else 0
            )
            height = available - caption_height - int(_GAP)
            if height <= 0:
                raise ValueError("picture and caption cannot fit in native content region")
            if picture.height > height:
                scale = height / picture.height
                picture.width = int(picture.width * scale)
                picture.height = height
            picture.left = region.left
            self._used_placeholder_idxs.add(region.placeholder_format.idx)
            self._region_picture_remaining[self._active_region] = remaining - 1
        self._slide_has_content = True
        self._advance_past(picture)
        alt_text = block.get("alt_text")
        if alt_text:
            try:
                picture._element.nvPicPr.cNvPr.set("descr", str(alt_text))
            except (AttributeError, TypeError):
                pass
        caption = block.get("caption")
        if caption:
            self._add_caption_box(
                str(caption), width=int(region.width if region is not None else picture.width)
            )

    def _add_equation(self, block: Block) -> None:
        mode = block.get("mode") or self._binding.get("equation_mode")
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
                    pptx_elem = omml_to_pptx_element(str(omml_raw))
                else:
                    pptx_elem = convert_latex_to_pptx_element(latex)

                font_size_pt = block.get("font_size_pt")
                font_pt = float(font_size_pt) if font_size_pt is not None else 18.0
                width = self._content_width()
                box = self._slide.shapes.add_textbox(
                    _MARGIN,
                    self._cursor,
                    width,
                    _estimate_box_height(latex, width, font_pt),
                )
                frame = box.text_frame
                frame.word_wrap = True
                p = frame.paragraphs[0]
                p._p.append(pptx_elem)

                self._slide_has_content = True
                self._cursor += int(box.height) + int(_GAP)
                if caption:
                    self._add_caption_box(str(caption), width=width)
                return
            except (EquationConversionError, Exception):
                if mode == "native-required":
                    raise
                # Fall back to high-resolution image rendering
                fallback_img = image
                if not fallback_img and latex:
                    try:
                        font_size_pt = block.get("font_size_pt")
                        size = float(font_size_pt) if font_size_pt is not None else 18.0
                        fallback_img = str(
                            render_latex_to_png(latex, font_size_pt=size)
                        )
                    except (ValueError, RuntimeError, OSError):
                        fallback_img = None
                if fallback_img:
                    resolved = _resolve_picture_source(str(fallback_img), self._binding)
                    if is_svg_asset(resolved):
                        fallback = block.get("fallback") or block.get("png")
                        if fallback:
                            resolved_png = _resolve_picture_source(str(fallback), self._binding)
                        else:
                            resolved_png = rasterize_svg_to_png(resolved, dpi=300)
                        picture = self._slide.shapes.add_picture(
                            str(resolved_png), _MARGIN, self._cursor
                        )
                        svg_bytes = resolved.read_bytes()
                        svg_part = get_or_add_svg_part(self._prs.part.package, svg_bytes)
                        svg_rId = self._slide.part.relate_to(svg_part, RELATIONSHIP_TYPE_IMAGE)
                        attach_svg_blip_extension(picture._element.blipFill.blip, svg_rId)
                    else:
                        picture = self._slide.shapes.add_picture(
                            str(resolved), _MARGIN, self._cursor
                        )
                    content_width = self._content_width()
                    if picture.width > content_width:
                        scale = content_width / picture.width
                        picture.width = int(picture.width * scale)
                        picture.height = int(picture.height * scale)
                    self._slide_has_content = True
                    self._advance_past(picture)
                    if caption:
                        self._add_caption_box(str(caption), width=int(picture.width))
                    return

        if mode == "image" or image:
            img_src = image
            if not img_src and latex:
                font_size_pt = block.get("font_size_pt")
                size = float(font_size_pt) if font_size_pt is not None else 18.0
                img_src = str(render_latex_to_png(latex, font_size_pt=size))
            resolved = _resolve_picture_source(str(img_src), self._binding)
            if is_svg_asset(resolved):
                fallback = block.get("fallback") or block.get("png")
                if fallback:
                    resolved_png = _resolve_picture_source(str(fallback), self._binding)
                else:
                    resolved_png = rasterize_svg_to_png(resolved, dpi=300)
                picture = self._slide.shapes.add_picture(
                    str(resolved_png), _MARGIN, self._cursor
                )
                svg_bytes = resolved.read_bytes()
                svg_part = get_or_add_svg_part(self._prs.part.package, svg_bytes)
                svg_rId = self._slide.part.relate_to(svg_part, RELATIONSHIP_TYPE_IMAGE)
                attach_svg_blip_extension(picture._element.blipFill.blip, svg_rId)
            else:
                picture = self._slide.shapes.add_picture(
                    str(resolved), _MARGIN, self._cursor
                )
            content_width = self._content_width()
            if picture.width > content_width:
                scale = content_width / picture.width
                picture.width = int(picture.width * scale)
                picture.height = int(picture.height * scale)
            self._slide_has_content = True
            self._advance_past(picture)
            if caption:
                self._add_caption_box(str(caption), width=int(picture.width))
            return

        # Monospace fallback
        font_size_pt = block.get("font_size_pt")
        font_pt = float(font_size_pt) if font_size_pt is not None else 18.0
        width = self._content_width()
        box = self._slide.shapes.add_textbox(
            _MARGIN, self._cursor, width, _estimate_box_height(latex, width, font_pt)
        )
        frame = box.text_frame
        frame.word_wrap = True
        frame.text = latex
        runs = frame.paragraphs[0].runs
        if runs:
            runs[0].font.name = "Courier New"
            runs[0].font.size = Pt(font_pt)
        self._slide_has_content = True
        self._cursor += int(box.height) + int(_GAP)
        if caption:
            self._add_caption_box(str(caption), width=width)

    # -- slide-boundary blocks ------------------------------------------------

    def _add_toc(self, block: Block) -> None:
        if self._slide_has_content:
            self.new_slide()

    def _add_pagebreak(self, block: Block) -> None:
        self.new_slide()

    # -- geometry -------------------------------------------------------------

    def _content_left(self) -> int:
        ph = self._region_placeholder()
        return int(ph.left) if ph is not None else int(_MARGIN)

    def _content_width(self) -> int:
        ph = self._region_placeholder()
        return int(ph.width) if ph is not None else int(self._prs.slide_width) - 2 * int(_MARGIN)

    def _content_bottom(self) -> int:
        bottom = int(self._prs.slide_height) - int(_MARGIN)
        for ph in self._slide.placeholders:
            role = self._placeholder_role(self._slide.slide_layout, ph)
            if role in ("footer", "date", "slide_number"):
                bottom = min(bottom, int(ph.top) - int(_GAP))
        region = self._region_placeholder()
        if region is not None:
            bottom = min(bottom, int(region.top + region.height))
        return bottom

    def _advance_past(self, shape: Any) -> None:
        self._cursor = max(self._cursor, int(shape.top) + int(shape.height) + int(_GAP))


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


_HANDLERS: dict[str, _Handler] = {
    "text": DeckWriter._add_text,
    "table": DeckWriter._add_table,
    "image": DeckWriter._add_picture_block,
    "plot": DeckWriter._add_picture_block,
    "equation": DeckWriter._add_equation,
    "toc": DeckWriter._add_toc,
    "pagebreak": DeckWriter._add_pagebreak,
}
