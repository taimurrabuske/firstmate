"""Markdown-to-blocks conversion for presenter.

Turns rich-text Markdown (a GFM subset, pure stdlib) into the shared
presenter content-block contract in one call:

- :func:`markdown_to_blocks` parses Markdown text into block dicts.
- :func:`markdown_file` reads a file first, then delegates.

The supported subset and its limitations are documented in
:mod:`presenter.markdown.converter`.
"""

from __future__ import annotations

from .converter import MarkdownError, markdown_file, markdown_to_blocks

__all__ = ["MarkdownError", "markdown_file", "markdown_to_blocks"]
