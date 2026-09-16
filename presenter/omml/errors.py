"""Exceptions for LaTeX, MathML, and OMML equation conversions."""

from __future__ import annotations


class EquationConversionError(ValueError):
    """Raised when LaTeX, MathML, or OMML equation conversion fails."""


class UnsupportedMacroError(EquationConversionError):
    """Raised when a LaTeX math string contains an unsupported macro or environment."""

    def __init__(self, macro: str, message: str | None = None) -> None:
        self.macro = macro
        msg = message or f"unsupported LaTeX macro or construct: {macro!r}"
        super().__init__(msg)
