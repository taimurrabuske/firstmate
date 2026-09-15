"""Convenience builders for common design-review slide layouts.

See :mod:`presenter.layouts.slides` for the full contract: every function
here returns a plain slide/layout spec dict (``title``, ``layout``,
``notes``, ``blocks``, ``placeholder_roles``) that prefers a native
PowerPoint layout and its placeholders over hand-placed geometry, and
degrades to a top-to-bottom DOCX section by stacking ``blocks`` in order.
"""

from __future__ import annotations

from .slides import (
    bullets_and_table,
    image_grid,
    split_half_text_images,
    title_bullets,
    title_single_image,
    two_column_bullets,
)

__all__ = [
    "title_bullets",
    "title_single_image",
    "split_half_text_images",
    "two_column_bullets",
    "bullets_and_table",
    "image_grid",
]
