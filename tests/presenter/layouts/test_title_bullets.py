"""Tests for presenter.layouts.title_bullets."""

from __future__ import annotations

import pytest

from presenter.layouts import title_bullets


def test_native_layout_and_body_role() -> None:
    slide = title_bullets("Overview", ["First point", "Second point"])
    assert slide["title"] == "Overview"
    assert slide["layout"] == "Title and Content"
    assert slide["notes"] is None
    assert slide["blocks"] == [
        {"type": "text", "style": "body", "text": "First point"},
        {"type": "text", "style": "body", "text": "Second point"},
    ]
    assert slide["placeholder_roles"] == {"body": [0, 1]}


def test_notes_pass_through() -> None:
    slide = title_bullets("Overview", ["A point"], notes="Speaker notes")
    assert slide["notes"] == "Speaker notes"


def test_empty_bullets_rejected() -> None:
    with pytest.raises(ValueError, match="bullets"):
        title_bullets("Overview", [])


def test_blank_bullet_rejected() -> None:
    with pytest.raises(ValueError, match="bullets\\[1\\]"):
        title_bullets("Overview", ["Fine", ""])
