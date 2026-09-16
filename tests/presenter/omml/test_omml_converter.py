"""Tests for LaTeX -> MathML -> OMML conversion pipeline."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from presenter.omml import (
    EquationConversionError,
    UnsupportedMacroError,
    can_convert_latex_to_omml,
    latex_to_mathml,
    latex_to_omml,
    mathml_to_omml,
    omml_to_docx_element,
    omml_to_pptx_element,
)

MATHML_NS = "http://www.w3.org/1998/Math/MathML"
OMML_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
A14_NS = "http://schemas.microsoft.com/office/drawing/2010/main"


def _assert_valid_omml_xml(omml_str: str) -> ET.Element:
    """Verify string is valid XML with <m:oMath> root."""
    root = ET.fromstring(omml_str)
    assert root.tag == f"{{{OMML_NS}}}oMath"
    return root


# =========================================================================
# Unit tests: latex_to_mathml
# =========================================================================


def test_latex_to_mathml_polynomial() -> None:
    latex = r"s^2 + 2\zeta\omega_n s + \omega_n^2"
    mathml_str = latex_to_mathml(latex)
    assert "<math" in mathml_str
    assert "msubsup" in mathml_str or "msub" in mathml_str
    assert "ζ" in mathml_str
    assert "ω" in mathml_str


def test_latex_to_mathml_fraction() -> None:
    latex = r"\frac{K \cdot \omega_0^2}{s^2 + \frac{\omega_0}{Q} s + \omega_0^2}"
    mathml_str = latex_to_mathml(latex)
    assert "<mfrac" in mathml_str
    assert "·" in mathml_str
    assert "ω" in mathml_str


def test_latex_to_mathml_roots() -> None:
    # Square root
    sqrt_str = latex_to_mathml(r"\sqrt{b^2 - 4ac}")
    assert "<msqrt" in sqrt_str

    # N-th root
    root_str = latex_to_mathml(r"\sqrt[3]{x^2 + 1}")
    assert "<mroot" in root_str
    assert "<mn>3</mn>" in root_str


def test_latex_to_mathml_greek_letters() -> None:
    latex = r"\alpha + \beta = \gamma \cdot \Delta + \Omega"
    mathml_str = latex_to_mathml(latex)
    assert "α" in mathml_str
    assert "β" in mathml_str
    assert "γ" in mathml_str
    assert "Δ" in mathml_str
    assert "Ω" in mathml_str


def test_latex_to_mathml_subscripts_and_superscripts() -> None:
    latex = r"V_{out} = A_v \cdot V_{in} + x_1^2"
    mathml_str = latex_to_mathml(latex)
    assert "<msub" in mathml_str
    assert "<msubsup" in mathml_str or ("<msub" in mathml_str and "<msup" in mathml_str)
    assert "out" in mathml_str or "o" in mathml_str


@pytest.mark.parametrize(
    "latex,subscript,superscript",
    [
        ("f'", None, "′"),
        ("f''", None, "′′"),
        ("f'''", None, "′′′"),
        ("f''_i", "i", "′′"),
        ("f_i'''", "i", "′′′"),
        ("f''_i^{2}", "i", "′′2"),
        ("f^2''", None, "2′′"),
        (r"f^{\prime\prime}", None, "′′"),
    ],
)
def test_prime_multiplicity_and_script_attachment(
    latex: str, subscript: str | None, superscript: str
) -> None:
    math = ET.fromstring(latex_to_mathml(latex))
    script = math[0]
    kind = "msup" if subscript is None else "msubsup"
    assert script.tag == f"{{{MATHML_NS}}}{kind}"
    assert "".join(script[0].itertext()) == "f"
    assert "".join(script[-1].itertext()) == superscript
    if subscript is not None:
        assert "".join(script[1].itertext()) == subscript

    omml = ET.fromstring(latex_to_omml(latex))
    assert "".join(omml.find(f".//{{{OMML_NS}}}sup").itertext()) == superscript
    if subscript is not None:
        assert "".join(omml.find(f".//{{{OMML_NS}}}sub").itertext()) == subscript


@pytest.mark.parametrize(
    "latex,expected",
    [
        (r"\text{steady state}", "steady state"),
        (r"\text{steady  state}", "steady  state"),
        (r"\text{  steady  state  }", "  steady  state  "),
        (r"\text{   }", "   "),
        (r"\text{ before {nested words} after }", " before nested words after "),
        (r"\text{gain \{low\} \& 50\%}", "gain {low} & 50%"),
        (r"\text{a < b & c > d}", "a < b & c > d"),
        (r"\text{rate \alpha per second}", "rate α per second"),
    ],
)
def test_text_whitespace_and_plain_style(latex: str, expected: str) -> None:
    math = ET.fromstring(latex_to_mathml(latex))
    assert "".join(math.itertext()) == expected
    assert math.find(f".//{{{MATHML_NS}}}mtext") is not None
    omml = ET.fromstring(latex_to_omml(latex))
    assert "".join(omml.itertext()) == expected
    for run in omml.findall(f".//{{{OMML_NS}}}r"):
        style = run.find(f"{{{OMML_NS}}}rPr/{{{OMML_NS}}}sty")
        assert style is not None
        assert style.get(f"{{{OMML_NS}}}val") == "p"
        text = run.find(f"{{{OMML_NS}}}t")
        if any(char.isspace() for char in text.text):
            assert text.get(XML_SPACE) == "preserve"


@pytest.mark.parametrize(
    "latex",
    [
        "x} + y",
        "x & y",
        r"x \\ y",
        r"\begin{matrix}",
        r"\begin{bmatrix} a & b",
        r"\begin{bmatrix} a & b \\ c & d",
        r"\begin{bmatrix} a & b \\ c & d \\",
        r"\begin{matrix}\begin{matrix}a\end{matrix}",
        r"\begin{matrix}a\end{pmatrix}",
        r"\begin{equation}x\end{equation*}",
        r"\begin{equation*}x\end{equation}",
        r"\begin{matrix}a\end{matrix}} discarded",
        r"\text{unclosed words",
        r"\text{\unknownmacro}",
        r"\frac{x}{y",
        r"\frac1} + y",
        r"\frac1&y",
        r"\frac1\\y",
        r"\begin{matrix}a}b\end{matrix}",
    ],
)
def test_rejects_partial_conversion(latex: str) -> None:
    with pytest.raises(EquationConversionError):
        latex_to_mathml(latex)
    with pytest.raises(EquationConversionError):
        latex_to_omml(latex)
    assert can_convert_latex_to_omml(latex) is False


def test_matrix_cells_retain_semantics() -> None:
    latex = r"\begin{bmatrix} f'' & \text{ steady state } \\ c & d \end{bmatrix} + z"
    math = ET.fromstring(latex_to_mathml(latex))
    rows = math.findall(f".//{{{MATHML_NS}}}mtr")
    assert [["".join(cell.itertext()) for cell in row] for row in rows] == [
        ["f′′", " steady state "],
        ["c", "d"],
    ]
    assert "".join(math[-2].itertext()) == "+"
    assert "".join(math[-1].itertext()) == "z"
    omml = ET.fromstring(latex_to_omml(latex))
    rows = omml.findall(f".//{{{OMML_NS}}}mr")
    assert [["".join(cell.itertext()) for cell in row] for row in rows] == [
        ["f′′", " steady state "],
        ["c", "d"],
    ]


def test_latex_to_mathml_matrix() -> None:
    latex = r"\begin{bmatrix} a & b \\ c & d \end{bmatrix}"
    mathml_str = latex_to_mathml(latex)
    assert "<mfenced" in mathml_str
    assert 'open="["' in mathml_str
    assert 'close="]"' in mathml_str
    assert "<mtable" in mathml_str
    assert "<mtr" in mathml_str
    assert "<mtd" in mathml_str


def test_latex_to_mathml_pmatrix() -> None:
    latex = r"\begin{pmatrix} 1 & 0 \\ 0 & 1 \end{pmatrix}"
    mathml_str = latex_to_mathml(latex)
    assert 'open="("' in mathml_str
    assert 'close=")"' in mathml_str


def test_latex_to_mathml_cases() -> None:
    latex = r"\begin{cases} 1 & x \geq 0 \\ 0 & x < 0 \end{cases}"
    mathml_str = latex_to_mathml(latex)
    assert 'open="{"' in mathml_str
    assert "<mtable" in mathml_str
    assert "≥" in mathml_str


def test_latex_to_mathml_accents() -> None:
    latex = r"\dot{x}_1 + \ddot{x}_2 + \bar{y} + \hat{z}"
    mathml_str = latex_to_mathml(latex)
    assert "<mover" in mathml_str
    assert "˙" in mathml_str
    assert "¨" in mathml_str
    assert "¯" in mathml_str
    assert "^" in mathml_str


def test_latex_to_mathml_nary_operators() -> None:
    latex = r"\int_0^\infty e^{-st} dt = \sum_{n=1}^\infty a_n"
    mathml_str = latex_to_mathml(latex)
    assert "∫" in mathml_str
    assert "∑" in mathml_str
    assert "∞" in mathml_str


def test_latex_to_mathml_delimiters() -> None:
    latex = r"\left( \frac{s - z_1}{s - p_1} \right)"
    mathml_str = latex_to_mathml(latex)
    assert "<mfenced" in mathml_str
    assert "<mfrac" in mathml_str


def test_latex_to_mathml_unsupported_macro_raises() -> None:
    with pytest.raises(UnsupportedMacroError, match="unsupported LaTeX macro"):
        latex_to_mathml(r"\unknowncomplexmacro{x}")

    with pytest.raises(UnsupportedMacroError, match="unsupported LaTeX environment"):
        latex_to_mathml(r"\begin{tikzpicture} \draw (0,0) -- (1,1); \end{tikzpicture}")


def test_latex_to_mathml_empty_raises() -> None:
    with pytest.raises(EquationConversionError, match="cannot be empty"):
        latex_to_mathml("   ")


@pytest.mark.parametrize("environment", ["equation", "equation*"])
def test_equation_environment_wrapper(environment: str) -> None:
    latex = rf"\begin{{{environment}}}f''\end{{{environment}}}"
    assert latex_to_mathml(latex) == latex_to_mathml("f''")


def test_latex_to_mathml_strips_dollar_wrappers() -> None:
    mathml_str = latex_to_mathml(r"$E = mc^2$")
    assert "<math" in mathml_str
    mathml_str2 = latex_to_mathml(r"$$E = mc^2$$")
    assert "<math" in mathml_str2
    mathml_str3 = latex_to_mathml(r"\[ E = mc^2 \]")
    assert "<math" in mathml_str3


# =========================================================================
# Unit tests: mathml_to_omml
# =========================================================================


def test_mathml_to_omml_basic() -> None:
    mathml = '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>x</mi><mo>+</mo><mn>1</mn></math>'
    omml = mathml_to_omml(mathml)
    root = _assert_valid_omml_xml(omml)
    runs = root.findall(f"{{{OMML_NS}}}r")
    assert len(runs) == 3
    texts = [r.find(f"{{{OMML_NS}}}t").text for r in runs]  # type: ignore[union-attr]
    assert texts == ["x", "+", "1"]


def test_mathml_to_omml_fraction() -> None:
    mathml = (
        '<math xmlns="http://www.w3.org/1998/Math/MathML">'
        "<mfrac><mi>a</mi><mi>b</mi></mfrac>"
        "</math>"
    )
    omml = mathml_to_omml(mathml)
    root = _assert_valid_omml_xml(omml)
    f = root.find(f"{{{OMML_NS}}}f")
    assert f is not None
    assert f.find(f"{{{OMML_NS}}}num") is not None
    assert f.find(f"{{{OMML_NS}}}den") is not None


def test_mathml_to_omml_scripts() -> None:
    # Subscript
    mathml_sub = (
        '<math xmlns="http://www.w3.org/1998/Math/MathML">'
        "<msub><mi>x</mi><mn>1</mn></msub>"
        "</math>"
    )
    omml_sub = mathml_to_omml(mathml_sub)
    root_sub = _assert_valid_omml_xml(omml_sub)
    assert root_sub.find(f"{{{OMML_NS}}}sSub") is not None

    # Superscript
    mathml_sup = (
        '<math xmlns="http://www.w3.org/1998/Math/MathML">'
        "<msup><mi>x</mi><mn>2</mn></msup>"
        "</math>"
    )
    omml_sup = mathml_to_omml(mathml_sup)
    root_sup = _assert_valid_omml_xml(omml_sup)
    assert root_sup.find(f"{{{OMML_NS}}}sSup") is not None

    # Sub-Superscript
    mathml_subsup = (
        '<math xmlns="http://www.w3.org/1998/Math/MathML">'
        "<msubsup><mi>x</mi><mn>1</mn><mn>2</mn></msubsup>"
        "</math>"
    )
    omml_subsup = mathml_to_omml(mathml_subsup)
    root_subsup = _assert_valid_omml_xml(omml_subsup)
    assert root_subsup.find(f"{{{OMML_NS}}}sSubSup") is not None


def test_mathml_to_omml_radical() -> None:
    # Sqrt
    mathml_sqrt = (
        '<math xmlns="http://www.w3.org/1998/Math/MathML">'
        "<msqrt><mi>x</mi></msqrt>"
        "</math>"
    )
    omml_sqrt = mathml_to_omml(mathml_sqrt)
    root_sqrt = _assert_valid_omml_xml(omml_sqrt)
    rad = root_sqrt.find(f"{{{OMML_NS}}}rad")
    assert rad is not None
    radPr = rad.find(f"{{{OMML_NS}}}radPr")
    assert radPr is not None
    assert radPr.find(f"{{{OMML_NS}}}degHide") is not None

    # Mroot
    mathml_root = (
        '<math xmlns="http://www.w3.org/1998/Math/MathML">'
        "<mroot><mi>x</mi><mn>3</mn></mroot>"
        "</math>"
    )
    omml_root = mathml_to_omml(mathml_root)
    root_root = _assert_valid_omml_xml(omml_root)
    rad2 = root_root.find(f"{{{OMML_NS}}}rad")
    assert rad2 is not None
    deg = rad2.find(f"{{{OMML_NS}}}deg")
    assert deg is not None
    assert deg.find(f"{{{OMML_NS}}}r") is not None


def test_mathml_to_omml_fenced() -> None:
    mathml = (
        '<math xmlns="http://www.w3.org/1998/Math/MathML">'
        '<mfenced open="[" close="]"><mi>x</mi></mfenced>'
        "</math>"
    )
    omml = mathml_to_omml(mathml)
    root = _assert_valid_omml_xml(omml)
    d = root.find(f"{{{OMML_NS}}}d")
    assert d is not None
    dPr = d.find(f"{{{OMML_NS}}}dPr")
    assert dPr is not None
    beg = dPr.find(f"{{{OMML_NS}}}begChr")
    assert beg is not None and beg.get(f"{{{OMML_NS}}}val") == "["
    end = dPr.find(f"{{{OMML_NS}}}endChr")
    assert end is not None and end.get(f"{{{OMML_NS}}}val") == "]"


def test_mathml_to_omml_matrix() -> None:
    mathml = (
        '<math xmlns="http://www.w3.org/1998/Math/MathML">'
        '<mfenced open="[" close="]">'
        "<mtable>"
        "<mtr><mtd><mn>1</mn></mtd><mtd><mn>2</mn></mtd></mtr>"
        "<mtr><mtd><mn>3</mn></mtd><mtd><mn>4</mn></mtd></mtr>"
        "</mtable>"
        "</mfenced>"
        "</math>"
    )
    omml = mathml_to_omml(mathml)
    root = _assert_valid_omml_xml(omml)
    d = root.find(f"{{{OMML_NS}}}d")
    assert d is not None
    m = d.find(f".//{{{OMML_NS}}}m")
    assert m is not None
    rows = m.findall(f"{{{OMML_NS}}}mr")
    assert len(rows) == 2
    for r in rows:
        cells = r.findall(f"{{{OMML_NS}}}e")
        assert len(cells) == 2


def test_mathml_to_omml_accent() -> None:
    mathml = (
        '<math xmlns="http://www.w3.org/1998/Math/MathML">'
        '<mover accent="true"><mi>x</mi><mo>˙</mo></mover>'
        "</math>"
    )
    omml = mathml_to_omml(mathml)
    root = _assert_valid_omml_xml(omml)
    acc = root.find(f"{{{OMML_NS}}}acc")
    assert acc is not None
    accPr = acc.find(f"{{{OMML_NS}}}accPr")
    assert accPr is not None
    chr_elem = accPr.find(f"{{{OMML_NS}}}chr")
    assert chr_elem is not None and chr_elem.get(f"{{{OMML_NS}}}val") == "˙"


# =========================================================================
# End-to-end tests: latex_to_omml & XML validity
# =========================================================================


@pytest.mark.parametrize(
    "latex",
    [
        # Transfer function: 2nd order low-pass filter
        r"H(s) = \frac{K \cdot \omega_0^2}{s^2 + \frac{\omega_0}{Q} s + \omega_0^2}",
        # Pole/zero factorization
        r"\frac{(s - z_1)(s - z_2)}{(s - p_1)(s - p_2)}",
        # Differential equation
        r"\frac{d^2 y}{dt^2} + 2\zeta\omega_n \frac{dy}{dt} + \omega_n^2 y = f(t)",
        # Second-order state-space matrix equation
        r"\begin{bmatrix} \dot{x}_1 \\ \dot{x}_2 \end{bmatrix} = \begin{bmatrix} 0 & 1 \\ -\omega_n^2 & -2\zeta\omega_n \end{bmatrix} \begin{bmatrix} x_1 \\ x_2 \end{bmatrix} + \begin{bmatrix} 0 \\ 1 \end{bmatrix} u",
        # Transistor small-signal gm/ID
        r"g_m = \frac{2 I_D}{V_{ov}}",
        # Noise expression
        r"\overline{v_n^2} = 4 k_B T R \Delta f",
        # Integrals and limits
        r"\int_0^\infty e^{-st} f(t) dt",
    ],
)
def test_latex_to_omml_technical_corpus(latex: str) -> None:
    """Verify that every equation in the technical corpus converts to valid OMML."""
    assert can_convert_latex_to_omml(latex) is True
    omml = latex_to_omml(latex)
    root = _assert_valid_omml_xml(omml)
    assert len(root) > 0

    # Verify docx oxml parser accepts the wrapped element
    docx_elem = omml_to_docx_element(omml, display=True)
    assert docx_elem.tag.endswith("oMathPara")
    assert len(docx_elem) > 0

    # Verify pptx oxml parser accepts the wrapped element
    pptx_elem = omml_to_pptx_element(omml)
    assert pptx_elem.tag.endswith("m")
    assert len(pptx_elem) > 0


def test_can_convert_latex_to_omml_negative() -> None:
    assert can_convert_latex_to_omml(r"\unsupportedmacro{123}") is False
    assert can_convert_latex_to_omml("") is False
