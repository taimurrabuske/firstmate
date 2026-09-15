"""DOCX rendering for the presenter library.

Public entry point: :func:`render` turns a list of content block dicts,
optionally bound to a corporate .docx template through a TemplateBinding
dict, into a finished .docx document.

:func:`render_document` is the adapter that matches
:data:`presenter.core.render.Engine`'s ``(document, binding, output_path)
-> output_path`` shape, so this lane can dispatch through
:func:`presenter.core.render.render` with a full :class:`~presenter.core.spec.DocumentSpec`
rather than a flat block list.  Call :func:`register` once (an application
entry point, not this package's import) to plug it into that registry;
importing this package alone never mutates the shared registry, so tests
that assert on the stub state are unaffected by merely importing it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from presenter.render_docx.engine import render

__all__ = ["render", "render_document", "register"]


def _flatten_document(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a normalized document dict's slides into one ordered block list.

    Each ``SlideSpec`` is a docx section: a non-empty slide title becomes a
    ``heading1`` text block ahead of the slide's own blocks.  No implicit
    page break is inserted between slides; add an explicit ``pagebreak()``
    block where one is wanted.
    """
    blocks: list[dict[str, Any]] = []
    for slide in document.get("slides", []):
        title = slide.get("title")
        if title:
            blocks.append({"type": "text", "style": "heading1", "text": title})
        blocks.extend(slide.get("blocks", []))
    return blocks


def render_document(
    document: dict[str, Any], binding: dict[str, Any], output_path: Path
) -> Path:
    """Engine adapter: render a normalized document dict through :func:`render`.

    ``document`` is the dict :meth:`~presenter.core.spec.DocumentSpec.to_dict`
    produces (document-level fields plus ``slides``), not the flat block
    list :func:`render` itself takes; this function bridges the two shapes.
    ``render`` returns a plain summary dict rather than the path, so this
    adapter reports the path from that summary instead.
    """
    blocks = _flatten_document(document)
    summary = render(blocks, binding, output_path)
    return Path(summary["output_path"])


def register(*, replace: bool = False) -> None:
    """Register :func:`render_document` as the ``"docx"`` engine.

    Import :mod:`presenter.core.render` lazily so importing this package
    never touches the shared registry on its own.
    """
    from presenter.core.render import register_engine

    register_engine("docx", render_document, replace=replace)
