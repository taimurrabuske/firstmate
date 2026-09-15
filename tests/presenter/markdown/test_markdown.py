"""Tests for the Markdown-to-blocks converter (presenter.markdown)."""

from __future__ import annotations

from pathlib import Path

import pytest

from presenter.core.blocks import validate_blocks
from presenter.core.errors import PresenterError
from presenter.markdown import MarkdownError, markdown_file, markdown_to_blocks


def convert(markdown: str) -> list[dict]:
    """Convert and assert every produced block satisfies the shared contract."""
    blocks = markdown_to_blocks(markdown)
    return validate_blocks(blocks)


# --------------------------------------------------------------------------
# Empty input
# --------------------------------------------------------------------------


def test_empty_and_whitespace_input_return_no_blocks() -> None:
    assert markdown_to_blocks("") == []
    assert convert("   \n\t\n  \n") == []
    assert markdown_to_blocks("\n\n\n") == []


def test_frontmatter_only_document_returns_no_blocks() -> None:
    assert convert("---\ntitle: x\n---\n") == []


# --------------------------------------------------------------------------
# Headings and paragraphs
# --------------------------------------------------------------------------


def test_atx_headings_map_to_heading_styles_with_clamp() -> None:
    blocks = convert("# One\n## Two\n### Three\n#### Four\n##### Five\n###### Six")
    styles = [block["style"] for block in blocks]
    assert styles == [
        "heading1",
        "heading2",
        "heading2",
        "heading2",
        "heading2",
        "heading2",
    ]
    assert [block["text"] for block in blocks] == [
        "One",
        "Two",
        "Three",
        "Four",
        "Five",
        "Six",
    ]


def test_heading_closing_hashes_require_preceding_whitespace() -> None:
    blocks = convert("## Kept ##\n### C#")
    assert [block["text"] for block in blocks] == ["Kept", "C#"]


def test_paragraph_lines_merge_into_one_body_block() -> None:
    blocks = convert("first wrapped line\nsecond wrapped line\n\nnew paragraph")
    assert blocks == [
        {
            "type": "text",
            "style": "body",
            "text": "first wrapped line second wrapped line",
        },
        {"type": "text", "style": "body", "text": "new paragraph"},
    ]


# --------------------------------------------------------------------------
# Inline markup
# --------------------------------------------------------------------------


def test_inline_markup_is_stripped_to_plain_text() -> None:
    blocks = convert("**bold** and __bold__ and *it* and _it_ and `code` and ~~gone~~")
    assert blocks[0]["text"] == "bold and bold and it and it and code and gone"


def test_links_and_inline_images_keep_text_drop_target() -> None:
    blocks = convert(
        "see [the docs](http://example.com/a) and ![pic](img/x.png) inline"
    )
    assert blocks[0]["text"] == "see the docs and pic inline"


def test_underscore_italics_not_recognized_inside_words() -> None:
    blocks = convert("snake_case_name stays whole")
    assert blocks[0]["text"] == "snake_case_name stays whole"


def test_backslash_escapes_survive_inline_stripping() -> None:
    blocks = convert("\\*not bold\\* and \\_not italic\\_ and a\\|pipe")
    assert blocks[0]["text"] == "*not bold* and _not italic_ and a|pipe"


def test_code_span_keeps_inner_markup_literally() -> None:
    blocks = convert("use `**this**` verbatim")
    assert blocks[0]["text"] == "use **this** verbatim"


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------


def test_pipe_table_without_alignment_colons_has_null_alignments() -> None:
    blocks = convert("| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |")
    assert blocks == [
        {
            "type": "table",
            "caption": None,
            "headers": ["A", "B"],
            "rows": [["1", "2"], ["3", "4"]],
            "style": "grid",
            "alignments": None,
        }
    ]


def test_pipe_table_with_alignment_row_records_alignments() -> None:
    blocks = convert("| L | C | R |\n|:-|:-:|-:|\n| a | b | c |")
    assert blocks[0]["alignments"] == ["left", "center", "right"]
    assert blocks[0]["headers"] == ["L", "C", "R"]


def test_mixed_alignment_row_defaults_unspecified_columns_to_left() -> None:
    blocks = convert("| A | B | C |\n|---|:-:|---|\n| 1 | 2 | 3 |")
    assert blocks[0]["alignments"] == ["left", "center", "left"]


def test_table_rows_pad_and_truncate_to_header_width() -> None:
    blocks = convert("| A | B |\n|---|---|\n| short |\n| extra | cells | here |")
    assert blocks[0]["rows"] == [["short", ""], ["extra", "cells"]]


def test_table_optional_leading_and_trailing_pipes() -> None:
    blocks = convert("A | B\n--- | ---\n1 | 2")
    assert blocks[0]["headers"] == ["A", "B"]
    assert blocks[0]["rows"] == [["1", "2"]]


def test_table_cells_strip_inline_markup_and_keep_escaped_pipes() -> None:
    blocks = convert("| Name | Note |\n|---|---|\n| **Big** | a \\| b |")
    assert blocks[0]["rows"] == [["Big", "a | b"]]


def test_table_with_header_but_no_body_rows() -> None:
    blocks = convert("| A | B |\n|---|---|")
    assert blocks[0]["rows"] == []


def test_pipe_line_without_delimiter_row_stays_a_paragraph() -> None:
    blocks = convert("a | b\nplain | text")
    assert blocks == [{"type": "text", "style": "body", "text": "a | b plain | text"}]


# --------------------------------------------------------------------------
# Lists
# --------------------------------------------------------------------------


def test_bullet_list_items_become_prefixed_text_blocks() -> None:
    blocks = convert("- one\n- two\n+ three\n* four")
    assert [block["text"] for block in blocks] == [
        "\u2022 one",
        "\u2022 two",
        "\u2022 three",
        "\u2022 four",
    ]
    assert all(block["style"] == "body" for block in blocks)


def test_ordered_list_items_keep_their_written_numbers() -> None:
    blocks = convert("3. third\n4) fourth")
    assert [block["text"] for block in blocks] == ["3. third", "4) fourth"]


def test_nested_list_items_indent_two_spaces_per_level() -> None:
    blocks = convert("- top\n  - child\n    - grandchild\n- top again")
    assert [block["text"] for block in blocks] == [
        "\u2022 top",
        "  \u2022 child",
        "    \u2022 grandchild",
        "\u2022 top again",
    ]


def test_lazy_continuation_extends_the_previous_item() -> None:
    blocks = convert("- item with\ncontinuation line\n- next")
    assert [block["text"] for block in blocks] == [
        "\u2022 item with continuation line",
        "\u2022 next",
    ]


def test_blank_line_ends_the_list() -> None:
    blocks = convert("- one\n\n- two after blank")
    assert len(blocks) == 2
    assert blocks[0]["text"] == "\u2022 one"


def test_list_item_inline_markup_is_stripped() -> None:
    blocks = convert("- **bold** and `code` item")
    assert blocks[0]["text"] == "\u2022 bold and code item"


# --------------------------------------------------------------------------
# Fenced code blocks
# --------------------------------------------------------------------------


def test_backtick_fence_preserves_content_verbatim() -> None:
    markdown = "```python\ndef f(x):\n    return x * 2\n```"
    blocks = convert(markdown)
    assert blocks == [
        {"type": "text", "style": "body", "text": "def f(x):\n    return x * 2"}
    ]


def test_tilde_fence_and_inline_markup_left_literal() -> None:
    blocks = convert("~~~\n**not bold** `not code`\n~~~")
    assert blocks[0]["text"] == "**not bold** `not code`"


def test_indented_fence_dedents_content_by_opener_indent() -> None:
    markdown = "   ```\n   indented\n     deeper\n```-level\n   ```"
    blocks = convert(markdown)
    assert blocks[0]["text"] == "indented\n  deeper\n```-level"


def test_unterminated_fence_takes_rest_of_document() -> None:
    blocks = convert("```\nline one\nline two")
    assert blocks[0]["text"] == "line one\nline two"


# --------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------


def test_standalone_image_becomes_image_block_with_alt_caption() -> None:
    blocks = convert("![Schematic](img/ldo.png)")
    assert blocks == [
        {
            "type": "image",
            "source": "img/ldo.png",
            "width_in": None,
            "caption": "Schematic",
        }
    ]


def test_image_without_alt_gets_null_caption() -> None:
    blocks = convert("![](img/x.png)")
    assert blocks[0]["caption"] is None
    assert blocks[0]["source"] == "img/x.png"


def test_standalone_image_with_title_drops_the_title() -> None:
    blocks = convert('![alt](img/x.png "the title")')
    assert blocks[0]["source"] == "img/x.png"


def test_image_with_empty_target_raises_markdown_error() -> None:
    with pytest.raises(MarkdownError) as excinfo:
        convert("![alt]()")
    assert isinstance(excinfo.value, PresenterError)
    assert "line 1" in str(excinfo.value)


# --------------------------------------------------------------------------
# Thematic breaks and quotes
# --------------------------------------------------------------------------


@pytest.mark.parametrize("break_line", ["---", "***", "___"])
def test_thematic_breaks_become_pagebreaks(break_line: str) -> None:
    blocks = convert(f"before\n\n{break_line}\n\nafter")
    assert [block["type"] for block in blocks] == ["text", "pagebreak", "text"]


def test_dash_break_after_paragraph_ends_the_paragraph() -> None:
    blocks = convert("Title\n---\n\nbody")
    assert [block["type"] for block in blocks] == ["text", "pagebreak", "text"]
    assert blocks[0]["text"] == "Title"


def test_block_quote_markers_stripped_into_body_text() -> None:
    blocks = convert("> quoted **bold** line\n> more\n\nafter")
    assert blocks[0] == {
        "type": "text",
        "style": "body",
        "text": "quoted bold line more",
    }


# --------------------------------------------------------------------------
# Mixed documents and the file wrapper
# --------------------------------------------------------------------------


def test_mixed_agent_report_document() -> None:
    markdown = """# Load-step report

The regulator passed **all** checks with `python -m pytest`.

## Results

| Check | Result |
|-------|:------:|
| assert | ok |
| timing | ok |

- stable across corners
- ripple within budget

```text
PASS 12 / 12
```

![Scope capture](artifacts/scope.png)

---

Follow-up items live in the backlog.
"""
    blocks = convert(markdown)
    assert [block["type"] for block in blocks] == [
        "text",
        "text",
        "text",
        "table",
        "text",
        "text",
        "text",
        "image",
        "pagebreak",
        "text",
    ]
    assert blocks[3]["headers"] == ["Check", "Result"]
    assert blocks[3]["rows"] == [["assert", "ok"], ["timing", "ok"]]
    assert blocks[3]["alignments"] == ["left", "center"]
    assert blocks[4]["text"] == "\u2022 stable across corners"
    assert blocks[6]["text"] == "PASS 12 / 12"
    assert blocks[7]["source"] == "artifacts/scope.png"
    assert blocks[9]["text"] == "Follow-up items live in the backlog."


def test_markdown_file_reads_and_delegates(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text("# Title\n\nBody text.\n", encoding="utf-8")
    blocks = markdown_file(path)
    assert blocks == [
        {"type": "text", "style": "heading1", "text": "Title"},
        {"type": "text", "style": "body", "text": "Body text."},
    ]


def test_non_string_input_raises_markdown_error() -> None:
    with pytest.raises(MarkdownError):
        markdown_to_blocks(None)  # type: ignore[arg-type]
