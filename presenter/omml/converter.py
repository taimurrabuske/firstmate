"""High-level conversion and XML element generation for Office Math (OMML)."""

from __future__ import annotations

from typing import Any

from docx.oxml import parse_xml as docx_parse_xml
from pptx.oxml import parse_xml as pptx_parse_xml

from presenter.omml.errors import EquationConversionError
from presenter.omml.latex_to_mathml import latex_to_mathml
from presenter.omml.mathml_to_omml import OMML_NS, mathml_to_omml

A14_NS = "http://schemas.microsoft.com/office/drawing/2010/main"


def latex_to_omml(latex: str) -> str:
    """Convert a LaTeX mathematical expression string into an OMML (<m:oMath>) XML string.

    Args:
        latex: Standard LaTeX mathematical expression (e.g. 'E = mc^2' or r'\\frac{1}{s}').

    Returns:
        XML string of the OMML (<m:oMath> root).

    Raises:
        UnsupportedMacroError: If the expression contains complex/unsupported macros.
        EquationConversionError: If parsing or conversion fails.
    """
    mathml_xml = latex_to_mathml(latex)
    return mathml_to_omml(mathml_xml)


def can_convert_latex_to_omml(latex: str) -> bool:
    """Return True if `latex` can be successfully converted to OMML, False otherwise."""
    try:
        latex_to_omml(latex)
        return True
    except (EquationConversionError, ValueError, TypeError):
        return False


def omml_to_docx_element(omml_str: str, display: bool = True) -> Any:
    """Wrap OMML XML string into a python-docx OxmlElement.

    Args:
        omml_str: OMML XML string (<m:oMath> root).
        display: If True, wraps inside <m:oMathPara> for display math.

    Returns:
        python-docx OxmlElement ready to append to a paragraph.
    """
    omml_clean = omml_str.strip()
    if display:
        xml_wrapper = f'<m:oMathPara xmlns:m="{OMML_NS}">{omml_clean}</m:oMathPara>'
    else:
        xml_wrapper = omml_clean
    return docx_parse_xml(xml_wrapper)


def omml_to_pptx_element(omml_str: str) -> Any:
    """Wrap OMML XML string into a python-pptx DrawingML text math container (<a14:m>).

    Args:
        omml_str: OMML XML string (<m:oMath> root).

    Returns:
        python-pptx OxmlElement ready to append to a slide shape paragraph.
    """
    omml_clean = omml_str.strip()
    xml_wrapper = (
        f'<a14:m xmlns:a14="{A14_NS}" xmlns:m="{OMML_NS}">{omml_clean}</a14:m>'
    )
    return pptx_parse_xml(xml_wrapper)


def convert_latex_to_docx_element(latex: str, display: bool = True) -> Any:
    """Convert LaTeX string to a python-docx OMML OxmlElement."""
    omml = latex_to_omml(latex)
    return omml_to_docx_element(omml, display=display)


def convert_latex_to_pptx_element(latex: str) -> Any:
    """Convert LaTeX string to a python-pptx DrawingML text math container OxmlElement."""
    omml = latex_to_omml(latex)
    return omml_to_pptx_element(omml)
