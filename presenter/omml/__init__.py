"""Office Math (OMML) conversion package for presenter."""

from __future__ import annotations

from presenter.omml.converter import (
    can_convert_latex_to_omml,
    convert_latex_to_docx_element,
    convert_latex_to_pptx_element,
    latex_to_omml,
    omml_to_docx_element,
    omml_to_pptx_element,
)
from presenter.omml.errors import EquationConversionError, UnsupportedMacroError
from presenter.omml.latex_to_mathml import latex_to_mathml
from presenter.omml.mathml_to_omml import mathml_to_omml

__all__ = [
    "EquationConversionError",
    "UnsupportedMacroError",
    "can_convert_latex_to_omml",
    "convert_latex_to_docx_element",
    "convert_latex_to_pptx_element",
    "latex_to_mathml",
    "latex_to_omml",
    "mathml_to_omml",
    "omml_to_docx_element",
    "omml_to_pptx_element",
]
