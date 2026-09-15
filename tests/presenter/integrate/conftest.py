"""Shared fixtures for presenter integration tests."""

from __future__ import annotations

from typing import Iterator

import pytest

from presenter.core.render import _engines, _stubs


@pytest.fixture(autouse=True)
def _restore_registry() -> Iterator[None]:
    """Leave presenter.core.render's module-level registry as found.

    Mirrors tests/presenter/core/test_render.py's fixture of the same name:
    these tests call presenter.render_docx.register(), which mutates the
    shared registry, so it must not leak into other test modules.
    """
    saved_engines, saved_stubs = dict(_engines), set(_stubs)
    yield
    _engines.clear()
    _engines.update(saved_engines)
    _stubs.clear()
    _stubs.update(saved_stubs)
