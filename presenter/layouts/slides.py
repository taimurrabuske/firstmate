"""Convenience builders for common design-review slide layouts.

Each function returns one slide/layout spec dict: a plain, JSON-serializable
structure accepted losslessly by :class:`presenter.core.spec.SlideSpec`,
including ``placeholder_roles``, which maps each native content region to
its block indices, and the optional ``columns`` image-grid hint.
No ``presenter.core`` import is needed here or by callers: every returned
block dict has exactly the shape
``presenter.core.blocks`` would produce, so it composes with the core API
(``SlideSpec.from_dict``, ``DocumentBuilder.add``) once the caller is ready
to validate it, and it also stands alone as plain data.

Library principle: prefer native PowerPoint layouts and placeholders over
hand-placed geometry.  ``layout`` names the closest native slide layout
(the kind already shipped in real PowerPoint masters, e.g. "Title and
Content", "Two Content", "Comparison", "Picture with Caption").
``presenter.render_pptx`` already resolves this today: ``render_document``
looks the name up by exact match against the bound template's slide
masters (``DeckWriter._resolve_layout``), so picking the right ``layout``
value is load-bearing now, not just forward-looking. The :func:`image_grid`
helper has no native layout equivalent; its unimplemented custom-placement
hint is called out in its own docstring.

``presenter.render_pptx`` routes ``left`` and ``right`` to the peer native
content placeholders of Two Content or Comparison (and compatible custom
layouts). Text fills its own placeholder; images and tables use that
placeholder's geometry. Comparison headings fill the native heading
placeholders above their columns. A missing or overlapping peer layout
raises rather than silently collapsing two columns into one. ``grid`` and
``columns`` remain preserved hints only; image-grid placement is not implemented.

The slide's own ``title`` field always carries the native title
placeholder; it is never repeated in ``blocks`` or ``placeholder_roles``.

Every function degrades gracefully to a DOCX section: rendering only needs
``title`` and the flat ``blocks`` list, which is already in top-to-bottom
reading order (first region, then the next), so a DOCX engine that simply
stacks blocks vertically (as ``presenter.render_docx`` does today) produces
a sensible read without mapping ``layout``/``placeholder_roles`` to Word
geometry. DOCX retains that vertical fallback.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

__all__ = [
    "title_bullets",
    "title_single_image",
    "split_half_text_images",
    "two_column_bullets",
    "bullets_and_table",
    "image_grid",
]

_SIDES: tuple[str, ...] = ("left", "right")

_CellValue = Any


def _validate_side(side: str) -> str:
    if side not in _SIDES:
        raise ValueError(f"side must be one of {_SIDES}, got {side!r}")
    return side


def _require_str_list(name: str, values: Sequence[str]) -> list[str]:
    is_sequence = isinstance(values, Sequence) and not isinstance(values, (str, bytes))
    if not is_sequence or not values:
        raise ValueError(f"{name} must be a non-empty list of strings")
    for i, value in enumerate(values):
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name}[{i}] must be a non-empty string")
    return list(values)


def _require_str(name: str, value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _text(content: str, style: str = "body") -> dict[str, Any]:
    return {"type": "text", "style": style, "text": content}


def _image(
    source: str, *, width_in: float | None = None, caption: str | None = None
) -> dict[str, Any]:
    return {"type": "image", "source": source, "width_in": width_in, "caption": caption}


def _table(
    headers: Sequence[str],
    rows: Sequence[Sequence[_CellValue]],
    *,
    caption: str | None = None,
    style: str = "grid",
    alignments: Sequence[str] | None = None,
) -> dict[str, Any]:
    headers = list(headers)
    if not headers:
        raise ValueError("table_headers must be a non-empty list of strings")
    normalized_rows: list[list[_CellValue]] = []
    for i, row in enumerate(rows):
        row = list(row)
        if len(row) != len(headers):
            raise ValueError(
                f"table_rows[{i}] has {len(row)} value(s) but there are "
                f"{len(headers)} header(s)"
            )
        normalized_rows.append(row)
    return {
        "type": "table",
        "caption": caption,
        "headers": headers,
        "rows": normalized_rows,
        "style": style,
        "alignments": list(alignments) if alignments is not None else None,
    }


def _slide_spec(
    title: str,
    layout: str,
    blocks: list[dict[str, Any]],
    placeholder_roles: Mapping[str, Sequence[int]],
    *,
    notes: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    roles = {role: list(indices) for role, indices in placeholder_roles.items()}
    spec: dict[str, Any] = {
        "title": _require_str("title", title),
        "layout": layout,
        "notes": notes,
        "blocks": blocks,
        "placeholder_roles": roles,
    }
    spec.update(extra)
    return spec


def title_bullets(
    title: str,
    bullets: Sequence[str],
    *,
    notes: str | None = None,
) -> dict[str, Any]:
    """Title plus a single bulleted-text region.

    Native layout: "Title and Content" (one title placeholder, one body
    content placeholder; the standard PowerPoint layout for a single block
    of talking points).  Each bullet becomes its own ``body``-style text
    block under the ``"body"`` placeholder role; this shape has only one
    content region, so it already renders fully as intended on both
    engines today - ``presenter.render_pptx`` appends each bullet as its
    own paragraph in the body placeholder, and DOCX stacks them as
    consecutive paragraphs (no native bulleted-list styling until the DOCX
    engine grows one).
    """
    bullets = _require_str_list("bullets", bullets)
    blocks = [_text(b) for b in bullets]
    return _slide_spec(
        title,
        "Title and Content",
        blocks,
        {"body": range(len(blocks))},
        notes=notes,
    )


def title_single_image(
    title: str,
    image_source: str,
    *,
    width_in: float | None = None,
    caption: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Title plus one image, optionally captioned.

    Native layout: "Picture with Caption" (title, picture placeholder, and
    a caption region).  Leave ``width_in`` unset and
    ``presenter.render_pptx`` inserts the image straight into the layout's
    picture placeholder today; passing ``width_in`` explicitly sizes the
    picture but opts out of the placeholder, matching how an explicit
    width already behaves everywhere else in this library.  The image
    block's own ``caption`` always prints as a text box under the picture;
    the engine does not yet target the layout's own caption-role
    placeholder specifically, so a template's caption styling on that
    placeholder is not picked up until it does.
    """
    image_source = _require_str("image_source", image_source)
    blocks = [_image(image_source, width_in=width_in, caption=caption)]
    return _slide_spec(
        title,
        "Picture with Caption",
        blocks,
        {"picture": [0]},
        notes=notes,
    )


def split_half_text_images(
    title: str,
    bullets: Sequence[str],
    image_sources: Sequence[str],
    *,
    side: str = "right",
    notes: str | None = None,
) -> dict[str, Any]:
    """Half the slide bulleted text, half the slide images.

    Native layout: "Two Content" (title plus two side-by-side content
    placeholders).  ``side`` names which half the images occupy; text
    takes the other half.  In ``blocks`` the ``"left"`` region's content
    always comes first regardless of which half it is, so DOCX still reads
    top-to-bottom in on-slide left-to-right order. PPTX fits the images
    into their native peer content region, sharing its height when there
    are multiple images, while the text fills the other placeholder.
    """
    _validate_side(side)
    bullets = _require_str_list("bullets", bullets)
    image_sources = _require_str_list("image_sources", image_sources)
    text_blocks = [_text(b) for b in bullets]
    image_blocks = [_image(s) for s in image_sources]
    if side == "right":
        left_blocks, right_blocks = text_blocks, image_blocks
    else:
        left_blocks, right_blocks = image_blocks, text_blocks
    blocks = left_blocks + right_blocks
    roles = {
        "left": range(len(left_blocks)),
        "right": range(len(left_blocks), len(blocks)),
    }
    return _slide_spec(title, "Two Content", blocks, roles, notes=notes)


def two_column_bullets(
    title: str,
    left_bullets: Sequence[str],
    right_bullets: Sequence[str],
    *,
    left_heading: str | None = None,
    right_heading: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Two side-by-side bulleted-text columns, each with an optional heading.

    Native layout: "Comparison" when either column has a heading (its two
    content placeholders each sit under their own heading placeholder,
    which is exactly what a headed column needs); plain "Two Content"
    otherwise.  A column heading, when given, becomes a ``heading2``-style
    text block leading that column's blocks. PPTX fills each column's
    native content placeholder and, on Comparison, its heading placeholder.
    """
    left_bullets = _require_str_list("left_bullets", left_bullets)
    right_bullets = _require_str_list("right_bullets", right_bullets)
    left_head = [_text(left_heading, style="heading2")] if left_heading else []
    left_blocks = left_head + [_text(b) for b in left_bullets]
    right_head = [_text(right_heading, style="heading2")] if right_heading else []
    right_blocks = right_head + [_text(b) for b in right_bullets]
    blocks = left_blocks + right_blocks
    roles = {
        "left": range(len(left_blocks)),
        "right": range(len(left_blocks), len(blocks)),
    }
    layout = "Comparison" if (left_heading or right_heading) else "Two Content"
    return _slide_spec(title, layout, blocks, roles, notes=notes)


def bullets_and_table(
    title: str,
    bullets: Sequence[str],
    table_headers: Sequence[str],
    table_rows: Sequence[Sequence[_CellValue]],
    *,
    table_caption: str | None = None,
    table_style: str = "grid",
    side: str = "right",
    notes: str | None = None,
) -> dict[str, Any]:
    """Half the slide bulleted text, half the slide a spec/data table.

    Native layout: "Two Content", the same two-placeholder layout used by
    :func:`split_half_text_images`; a table is just another content type a
    "Two Content" placeholder can hold.  ``side`` names which half the
    table occupies. PPTX keeps the caption and table inside that peer
    region, leaving the bullets in the other native placeholder on the
    first slide. Table continuations retain their region and repeat headers,
    but do not repeat the caption or bullets.
    """
    _validate_side(side)
    bullets = _require_str_list("bullets", bullets)
    text_blocks = [_text(b) for b in bullets]
    table_block = _table(
        table_headers, table_rows, caption=table_caption, style=table_style
    )
    if side == "right":
        left_blocks, right_blocks = text_blocks, [table_block]
    else:
        left_blocks, right_blocks = [table_block], text_blocks
    blocks = left_blocks + right_blocks
    roles = {
        "left": range(len(left_blocks)),
        "right": range(len(left_blocks), len(blocks)),
    }
    return _slide_spec(title, "Two Content", blocks, roles, notes=notes)


def image_grid(
    title: str,
    image_sources: Sequence[str],
    *,
    columns: int = 2,
    captions: Sequence[str | None] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """An N-up grid of images (screenshots, waveform snapshots, layout views).

    Custom-placement fallback: no standard PowerPoint layout offers an
    arbitrary image grid (native layouts top out at the two side-by-side
    placeholders in "Two Content"/"Comparison"), so this is the one shape
    in this package without a native-layout match.  ``layout`` is "Blank"
    (no placeholders to claim) and the returned spec carries a
    ``"columns"`` hint; computing actual grid geometry from ``columns`` and
    the image count is render-engine work, not implemented yet by either
    engine, so both currently just stack every image top to bottom -
    ``presenter.render_pptx`` free-flows each picture down the slide the
    same way DOCX stacks paragraphs.
    """
    image_sources = _require_str_list("image_sources", image_sources)
    if not isinstance(columns, int) or isinstance(columns, bool) or columns < 1:
        raise ValueError(f"columns must be a positive int, got {columns!r}")
    if captions is not None:
        if len(captions) != len(image_sources):
            raise ValueError(
                "captions must have the same length as image_sources when given"
            )
    else:
        captions = [None] * len(image_sources)
    blocks = [
        _image(source, caption=caption)
        for source, caption in zip(image_sources, captions)
    ]
    return _slide_spec(
        title,
        "Blank",
        blocks,
        {"grid": range(len(blocks))},
        notes=notes,
        columns=columns,
    )
