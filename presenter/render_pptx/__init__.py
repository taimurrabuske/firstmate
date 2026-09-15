"""PPTX rendering for the presenter library.

Public entry point: :func:`render` turns a list of content block dicts,
optionally bound to a corporate .pptx template through a TemplateBinding
dict, into a finished .pptx slide deck.

:func:`render_document` is the adapter that matches
:data:`presenter.core.render.Engine`'s ``(document, binding, output_path)
-> output_path`` shape, so this lane can dispatch through
:func:`presenter.core.render.render` with a full
:class:`~presenter.core.spec.DocumentSpec` rather than a flat block list.
Call :func:`register` once (an application entry point, not this package's
import) to plug it into that registry; importing this package alone never
mutates the shared registry, so tests that assert on the stub state are
unaffected by merely importing it.
"""

from __future__ import annotations

from presenter.render_pptx.engine import render, render_document

__all__ = ["register", "render", "render_document"]


def register(*, replace: bool = False) -> None:
    """Register :func:`render_document` as the ``"pptx"`` engine.

    Import :mod:`presenter.core.render` lazily so importing this package
    never touches the shared registry on its own.
    """
    from presenter.core.render import register_engine

    register_engine("pptx", render_document, replace=replace)
