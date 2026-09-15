"""Convert rich-text Markdown (a GFM subset) into presenter content blocks.

This module turns an agent's written Markdown output into the shared presenter
block contract (``presenter/README.md``) in one call, using only the standard
library.  Every returned block is passed through
:func:`presenter.core.blocks.validate_block`, so the output is always
normalized and contract-valid.

Supported block-level subset
----------------------------

- ATX headings (``#`` to ``######``): level 1 maps to ``heading1``, level 2 to
  ``heading2``, and levels 3-6 clamp to ``heading2`` because the contract only
  defines two heading styles.  A trailing closing sequence of ``#`` preceded
  by whitespace is stripped.
- GFM pipe tables: a header row followed by a delimiter row whose cells match
  ``:``/``-``/``:`` patterns.  Cell values are strings; inline markup inside a
  cell is stripped.  Column alignment from the delimiter row is recorded in
  the table block's ``alignments`` field (``left``/``center``/``right``);
  columns without an explicit alignment default to ``left``, and a delimiter
  row with no colons at all leaves ``alignments`` ``None``.  Rows with fewer
  cells than the header are padded with empty strings and rows with more are
  truncated, matching GFM.
- Fenced code blocks (``` or ~~~): the content is preserved verbatim as a
  single ``body`` text block with one source line per ``\\n`` (each content
  line loses only the opening fence's own indentation).  The contract's
  text styles have no monospace entry yet, so the fence's info string (such as
  ``python``) is dropped and the block carries no code styling.
- Standalone images (``![alt](path)`` alone on a line): an ``image`` block
  with ``source`` set to the path and the alt text as ``caption`` when
  non-empty.  An image with an empty target raises :class:`MarkdownError`.
- Thematic breaks (``---``, ``***``, ``___``): ``pagebreak`` blocks.  Unlike
  GFM, a break line always ends the preceding paragraph: setext headings are
  not supported, so ``Title`` followed by ``---`` yields a body paragraph and
  a page break, never a heading.
- Bullet lists (``-``, ``*``, ``+``) and ordered lists (``1.``, ``1)``): each
  item becomes its own ``body`` text block whose text is bullet-prefixed
  (``• item``; ordered items keep their number and delimiter as written).
  Nested items are indented two spaces per level; a non-blank unindented line
  directly after an item continues that item; a blank line ends the list.
- Block quotes (``> ``): the markers are stripped and the content becomes an
  ordinary body paragraph (no nested structure inside quotes).
- YAML front matter: a ``---`` ... ``---``/``...`` block at the very start of
  the document is skipped entirely.
- Plain paragraphs: consecutive text lines merge into one ``body`` text block
  with soft line breaks joined by a single space, matching GFM reflowing.

Supported inline markup (stripped to plain text everywhere, including table
cells and list items): ``**bold**``, ``__bold__``, ``*italic*``, ``_italic_``
(underscore emphasis is not recognized inside words, so ``snake_case`` is
safe), ``~~strikethrough~~``, ``inline code``, ``[link text](url)`` (keeps
the text, drops the URL), inline ``![alt](url)`` images inside a paragraph
(kept as their alt text), and backslash escapes of ASCII punctuation.

Not supported (kept as literal text or documented above): setext headings,
indented code blocks, raw HTML, reference links and images, autolinks,
footnotes, task-list checkboxes, nested block structures inside quotes, and
any third-party Markdown extensions.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from presenter.core.blocks import validate_block
from presenter.core.errors import PresenterError

__all__ = ["MarkdownError", "markdown_file", "markdown_to_blocks"]


class MarkdownError(PresenterError):
    """The Markdown input cannot be represented under the block contract."""


# --------------------------------------------------------------------------
# Inline markup
# --------------------------------------------------------------------------

# Backslash escapes are stashed as private-use sentinels before markup
# regexes run, then restored, so ``\\*not bold\\*`` survives literally.
_ESCAPABLE = r"\`*_{}[]()#+-.!|>~"
_ESCAPE_RE = re.compile(r"\\([" + re.escape(_ESCAPABLE) + r"])")
_STASH_BASE = "\ue000"
_CODE_STASH_BASE = "\ue001"

_IMAGE_INLINE_RE = re.compile(r"!\[([^\]]*)\]\(([^()\s]+)(?:\s+\"[^\"]*\")?\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^()\s]+)(?:\s+\"[^\"]*\")?\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)
_ITALIC_STAR_RE = re.compile(r"\*([^*\n]+)\*")
_ITALIC_UNDERSCORE_RE = re.compile(r"(?<![\w])_([^_\n]+)_(?![\w])")
_STRIKE_RE = re.compile(r"~~(.+?)~~", re.DOTALL)
_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")


def _stash_escapes(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        return _STASH_BASE + str(_ESCAPABLE.index(match.group(1))) + _STASH_BASE

    return _ESCAPE_RE.sub(_replace, text)


def _restore_escapes(text: str) -> str:
    return re.sub(
        _STASH_BASE + r"(\d+)" + _STASH_BASE,
        lambda match: _ESCAPABLE[int(match.group(1))],
        text,
    )


def _strip_inline(text: str) -> str:
    """Reduce one line of inline Markdown to plain text."""
    # Code spans come first: their content stays literal through every later
    # pass (backslash escapes are not processed inside code spans).
    code_spans: list[str] = []

    def _stash_code(match: re.Match[str]) -> str:
        code_spans.append(match.group(1))
        return _CODE_STASH_BASE + str(len(code_spans) - 1) + _CODE_STASH_BASE

    text = _CODE_SPAN_RE.sub(_stash_code, text)
    text = _stash_escapes(text)
    text = _IMAGE_INLINE_RE.sub(r"\1", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _BOLD_RE.sub(lambda match: match.group(1) or match.group(2), text)
    text = _ITALIC_STAR_RE.sub(r"\1", text)
    text = _ITALIC_UNDERSCORE_RE.sub(r"\1", text)
    text = _STRIKE_RE.sub(r"\1", text)
    text = _restore_escapes(text)
    return re.sub(
        _CODE_STASH_BASE + r"(\d+)" + _CODE_STASH_BASE,
        lambda match: code_spans[int(match.group(1))],
        text,
    ).strip()


# --------------------------------------------------------------------------
# Line classification
# --------------------------------------------------------------------------

_BLANK_RE = re.compile(r"^\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})(?:\s+(.*))?$")
_HR_RE = re.compile(r"^ {0,3}(?:(-{3,})|(\*{3,})|(_{3,}))\s*$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*([^`]*)$")
_BULLET_ITEM_RE = re.compile(r"^(\s*)([-*+])\s+(.*)$")
_ORDERED_ITEM_RE = re.compile(r"^(\s*)(\d{1,9})([.)])\s+(.*)$")
_QUOTE_RE = re.compile(r"^ {0,3}>\s?(.*)$")
_DELIMITER_CELL_RE = re.compile(r"^:?-+:?$")
_STANDALONE_IMAGE_RE = re.compile(r"^!\[([^\]]*)\]\(([^()\s]*)(?:\s+\"[^\"]*\")?\)\s*$")
_CLOSING_HASHES_RE = re.compile(r"\s+#+\s*$")


def _is_blank(line: str) -> bool:
    return _BLANK_RE.match(line) is not None


def _has_unescaped_pipe(line: str) -> bool:
    return re.search(r"(?<!\\)\|", line) is not None


def _is_delimiter_row(line: str) -> bool:
    """True when the line is a table delimiter row (``---`` / ``:---:`` cells)."""
    stripped = line.strip()
    if not stripped:
        return False
    cells = _split_table_row(stripped)
    if not cells:
        return False
    return all(_DELIMITER_CELL_RE.match(cell.replace(" ", "")) for cell in cells)


def _split_table_row(line: str) -> list[str]:
    """Split one pipe-table row into raw cell strings on unescaped pipes."""
    stripped = line.strip().removeprefix("|")
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in stripped:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            current.append(char)
            escaped = True
        elif char == "|":
            cells.append("".join(current))
            current = []
        else:
            current.append(char)
    cells.append("".join(current))
    return cells


def _is_list_item(line: str) -> bool:
    return (
        _BULLET_ITEM_RE.match(line) is not None
        or _ORDERED_ITEM_RE.match(line) is not None
    )


def _starts_block(line: str) -> bool:
    """True when the line cannot be a paragraph continuation line."""
    return (
        _is_blank(line)
        or _HEADING_RE.match(line) is not None
        or _HR_RE.match(line) is not None
        or _FENCE_RE.match(line) is not None
        or _QUOTE_RE.match(line) is not None
        or _is_list_item(line)
    )


# --------------------------------------------------------------------------
# Block producers
# --------------------------------------------------------------------------


def _strip_frontmatter(lines: list[str]) -> list[str]:
    if not lines or lines[0].strip() != "---":
        return lines
    for index in range(1, len(lines)):
        if lines[index].strip() in ("---", "..."):
            return lines[index + 1 :]
    return lines


def _fenced_code_block(lines: list[str], start: int) -> tuple[dict[str, Any], int]:
    opening = _FENCE_RE.match(lines[start])
    assert opening is not None
    fence = opening.group(1)
    close = fence[0] * len(fence)
    # Content lines are dedented by the opening fence's indentation.
    opener_indent = len(lines[start]) - len(lines[start].lstrip(" "))
    dedent = re.compile(rf"^ {{1,{opener_indent}}}") if opener_indent else None
    content_lines: list[str] = []
    index = start + 1
    while index < len(lines):
        line = lines[index]
        if line.strip() == close:
            return (
                {"type": "text", "style": "body", "text": "\n".join(content_lines)},
                index + 1,
            )
        content_lines.append(dedent.sub("", line, count=1) if dedent else line)
        index += 1
    # Unterminated fence: take everything to the end of the document.
    return {"type": "text", "style": "body", "text": "\n".join(content_lines)}, index


def _alignment_from_delimiter(cell: str) -> str:
    if cell.startswith(":") and cell.endswith(":"):
        return "center"
    if cell.endswith(":"):
        return "right"
    return "left"


def _table_block(lines: list[str], start: int) -> tuple[dict[str, Any], int]:
    headers = [
        _strip_inline(_clean_cell(cell))
        for cell in _split_table_row(lines[start].strip())
    ]
    delimiter_cells = [
        _alignment_from_delimiter(cell.replace(" ", ""))
        for cell in _split_table_row(lines[start + 1].strip())
    ]
    has_alignment = any(
        cell.replace(" ", "").startswith(":") or cell.replace(" ", "").endswith(":")
        for cell in _split_table_row(lines[start + 1].strip())
    )
    alignments: list[str] | None = delimiter_cells if has_alignment else None

    rows: list[list[str]] = []
    index = start + 2
    while (
        index < len(lines)
        and _has_unescaped_pipe(lines[index])
        and not _is_blank(lines[index])
    ):
        cells = [
            _strip_inline(_clean_cell(cell))
            for cell in _split_table_row(lines[index].strip())
        ]
        if len(cells) < len(headers):
            cells += [""] * (len(headers) - len(cells))
        elif len(cells) > len(headers):
            cells = cells[: len(headers)]
        rows.append(cells)
        index += 1

    block: dict[str, Any] = {
        "type": "table",
        "caption": None,
        "headers": headers,
        "rows": rows,
        "style": "grid",
        "alignments": alignments,
    }
    return block, index


def _clean_cell(cell: str) -> str:
    # A lone escaped pipe renders as a literal pipe character.
    cell = cell.replace("\\|", "|")
    return cell.strip()


def _list_blocks(lines: list[str], start: int) -> tuple[list[dict[str, Any]], int]:
    first = _BULLET_ITEM_RE.match(lines[start]) or _ORDERED_ITEM_RE.match(lines[start])
    assert first is not None
    base_indent = len(first.group(1))
    blocks: list[dict[str, Any]] = []
    index = start
    while index < len(lines):
        line = lines[index]
        bullet = _BULLET_ITEM_RE.match(line)
        ordered = _ORDERED_ITEM_RE.match(line)
        if bullet is None and ordered is None:
            if _is_blank(line) or not blocks:
                break
            # Lazy continuation of the previous item.
            blocks[-1]["text"] += " " + _strip_inline(line.strip())
            index += 1
            continue
        marker = bullet if bullet is not None else ordered
        indent = len(marker.group(1))
        if indent < base_indent:
            break
        level = max(0, (indent - base_indent) // 2)
        if bullet is not None:
            prefix, content = "\u2022 ", bullet.group(3)
        else:
            prefix, content = f"{ordered.group(2)}{ordered.group(3)} ", ordered.group(4)
        blocks.append(
            {
                "type": "text",
                "style": "body",
                "text": "  " * level + prefix + _strip_inline(content),
            }
        )
        index += 1
    return blocks, index


def _quote_paragraph(lines: list[str], start: int) -> tuple[dict[str, Any], int]:
    parts: list[str] = []
    index = start
    while index < len(lines):
        match = _QUOTE_RE.match(lines[index])
        if match is not None:
            parts.append(match.group(1))
        elif not _is_blank(lines[index]) and parts and not _starts_block(lines[index]):
            parts.append(lines[index].strip())  # lazy continuation
        else:
            break
        index += 1
    text = _strip_inline(" ".join(part.strip() for part in parts if part.strip()))
    return {"type": "text", "style": "body", "text": text}, index


def _paragraph_block(lines: list[str], start: int) -> tuple[dict[str, Any], int]:
    parts: list[str] = []
    index = start
    while (
        index < len(lines)
        and not _starts_block(lines[index])
        and not _starts_table(lines, index)
    ):
        if _STANDALONE_IMAGE_RE.match(lines[index].strip()):
            break
        parts.append(lines[index].strip())
        index += 1
    text = _strip_inline(" ".join(part for part in parts if part))
    return {"type": "text", "style": "body", "text": text}, index


def _starts_table(lines: list[str], index: int) -> bool:
    return (
        index + 1 < len(lines)
        and _has_unescaped_pipe(lines[index])
        and _is_delimiter_row(lines[index + 1])
    )


def _image_block(
    lines: list[str], start: int, line_number: int
) -> tuple[dict[str, Any], int]:
    match = _STANDALONE_IMAGE_RE.match(lines[start].strip())
    assert match is not None
    alt, target = match.group(1), match.group(2)
    if not target:
        raise MarkdownError(f"line {line_number}: image has an empty target path")
    return {"type": "image", "source": target, "caption": alt or None}, start + 1


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def markdown_to_blocks(text: str) -> list[dict[str, Any]]:
    """Parse a Markdown document (GFM subset) into presenter content blocks.

    See the module docstring for the supported subset and its limitations.
    Returns validated, normalized block dicts per the shared contract in
    ``presenter/README.md``; empty or whitespace-only input returns ``[]``.
    Raises :class:`MarkdownError` for input that cannot be represented.
    """
    if not isinstance(text, str):
        raise MarkdownError(
            f"expected markdown text as a string, got {type(text).__name__}"
        )
    lines = _strip_frontmatter(text.splitlines())
    blocks: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if _is_blank(line):
            index += 1
            continue
        line_number = index + 1
        fence = _FENCE_RE.match(line)
        if fence is not None:
            block, index = _fenced_code_block(lines, index)
            blocks.append(block)
            continue
        heading = _HEADING_RE.match(line)
        if heading is not None:
            content = _CLOSING_HASHES_RE.sub("", heading.group(2) or "")
            style = "heading1" if len(heading.group(1)) == 1 else "heading2"
            blocks.append(
                {"type": "text", "style": style, "text": _strip_inline(content)}
            )
            index += 1
            continue
        if _HR_RE.match(line) is not None:
            blocks.append({"type": "pagebreak"})
            index += 1
            continue
        if _starts_table(lines, index):
            block, index = _table_block(lines, index)
            blocks.append(block)
            continue
        if _QUOTE_RE.match(line) is not None:
            block, index = _quote_paragraph(lines, index)
            blocks.append(block)
            continue
        if _is_list_item(line):
            produced, index = _list_blocks(lines, index)
            blocks.extend(produced)
            continue
        if _STANDALONE_IMAGE_RE.match(line.strip()) is not None:
            block, index = _image_block(lines, index, line_number)
            blocks.append(block)
            continue
        block, index = _paragraph_block(lines, index)
        blocks.append(block)
    return [
        validate_block(block, location=f"markdown block {position}")
        for position, block in enumerate(blocks)
    ]


def markdown_file(path: str | Path) -> list[dict[str, Any]]:
    """Read a Markdown file and return its presenter content blocks."""
    return markdown_to_blocks(Path(path).read_text(encoding="utf-8"))
