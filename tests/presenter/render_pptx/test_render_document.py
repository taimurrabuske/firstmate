"""Tests for the core-engine contract adapter and registry registration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest
from pptx import Presentation

from presenter.core import DocumentBuilder
from presenter.core import render as core_render
from presenter.core.errors import RenderError
from presenter.render_pptx import render_document


def test_register_plugs_engine_into_core(pptx_engine: Any) -> None:
    from presenter.core.render import get_engine, is_engine_implemented

    assert is_engine_implemented("pptx")
    assert get_engine("pptx") is render_document


def test_register_replace_semantics_match_the_core_registry() -> None:
    from presenter.core.render import get_engine, register_engine, unregister_engine

    sentinel = lambda d, b, p: p  # noqa: E731
    register_engine("pptx", sentinel)
    try:
        with pytest.raises(RenderError, match="already registered"):
            import presenter.render_pptx

            presenter.render_pptx.register()
        presenter.render_pptx.register(replace=True)
        assert get_engine("pptx") is render_document
    finally:
        unregister_engine("pptx")


def test_core_render_dispatches_pptx_end_to_end(
    tmp_path: Path,
    make_template_pptx: Callable[..., Path],
    pptx_binding: Callable[..., dict],
    pptx_engine: Any,
) -> None:
    template = make_template_pptx(marker="Corporate Master")
    spec = (
        DocumentBuilder("LDO Deck")
        .slide("Contents")
        .add({"type": "toc"})
        .slide("Overview")
        .add({"type": "text", "style": "body", "text": "A 3.3 V LDO."})
        .build()
    )
    output = tmp_path / "deck.pptx"
    written = core_render(spec, pptx_binding(template=template), output)
    assert written == output
    prs = Presentation(str(output))
    assert [slide.shapes.title.text for slide in prs.slides] == [
        "Corporate Master",
        "Contents",
        "Overview",
    ]


def test_render_document_maps_titles_notes_and_layout(
    tmp_path: Path,
    pptx_binding: Callable[..., dict],
) -> None:
    output = tmp_path / "deck.pptx"
    document = {
        "title": "Deck",
        "slides": [
            {
                "title": "First",
                "notes": "speaker note",
                "blocks": [{"type": "text", "style": "body", "text": "body text"}],
            },
            {"title": "Second", "layout": "Title Only"},
        ],
    }
    written = render_document(document, pptx_binding(), output)
    assert written == output
    prs = Presentation(str(output))
    assert len(prs.slides) == 2
    first, second = prs.slides[0], prs.slides[1]
    assert first.shapes.title.text == "First"
    assert first.notes_slide.notes_text_frame.text == "speaker note"
    assert any(
        shape.has_text_frame and shape.text_frame.text == "body text"
        for shape in first.shapes
    )
    assert second.shapes.title.text == "Second"
    assert second.slide_layout.name == "Title Only"


def test_render_document_unknown_layout_raises(
    tmp_path: Path,
    pptx_binding: Callable[..., dict],
) -> None:
    document = {
        "title": "Deck",
        "slides": [{"title": "X", "layout": "No Such Layout"}],
    }
    with pytest.raises(ValueError, match="no slide layout named"):
        render_document(document, pptx_binding(), tmp_path / "deck.pptx")


def test_render_document_empty_document_writes_zero_slides(
    tmp_path: Path,
    pptx_binding: Callable[..., dict],
) -> None:
    output = tmp_path / "deck.pptx"
    render_document({"title": "Deck", "slides": []}, pptx_binding(), output)
    assert len(Presentation(str(output)).slides) == 0
