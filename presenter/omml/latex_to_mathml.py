"""Convert LaTeX mathematical expressions to W3C Presentation MathML."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from presenter.omml.errors import EquationConversionError, UnsupportedMacroError

MATHML_NS = "http://www.w3.org/1998/Math/MathML"

try:
    ET.register_namespace("", MATHML_NS)
except (ValueError, KeyError):
    pass

# Greek letters mapping
GREEK_LETTERS: dict[str, str] = {
    # Lowercase
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ϵ",
    "varepsilon": "ε",
    "zeta": "ζ",
    "eta": "η",
    "theta": "θ",
    "vartheta": "ϑ",
    "iota": "ι",
    "kappa": "κ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "xi": "ξ",
    "pi": "π",
    "varpi": "ϖ",
    "rho": "ρ",
    "varrho": "ϱ",
    "sigma": "σ",
    "varsigma": "ς",
    "tau": "τ",
    "upsilon": "υ",
    "phi": "ϕ",
    "varphi": "φ",
    "chi": "χ",
    "psi": "ψ",
    "omega": "ω",
    # Uppercase
    "Gamma": "Γ",
    "Delta": "Δ",
    "Theta": "Θ",
    "Lambda": "Λ",
    "Xi": "Ξ",
    "Pi": "Π",
    "Sigma": "Σ",
    "Upsilon": "Υ",
    "Phi": "Φ",
    "Psi": "Ψ",
    "Omega": "Ω",
}

# Mathematical symbols mapping
MATH_SYMBOLS: dict[str, str] = {
    "cdot": "·",
    "times": "×",
    "div": "÷",
    "pm": "±",
    "mp": "∓",
    "ast": "∗",
    "star": "⋆",
    "circ": "∘",
    "bullet": "•",
    "leq": "≤",
    "le": "≤",
    "geq": "≥",
    "ge": "≥",
    "neq": "≠",
    "ne": "≠",
    "approx": "≈",
    "equiv": "≡",
    "sim": "∼",
    "simeq": "≃",
    "cong": "≅",
    "propto": "∝",
    "in": "∈",
    "notin": "∉",
    "ni": "∋",
    "subset": "⊂",
    "subseteq": "⊆",
    "supset": "⊃",
    "supseteq": "⊇",
    "cap": "∩",
    "cup": "∪",
    "setminus": "∖",
    "to": "→",
    "rightarrow": "→",
    "leftarrow": "←",
    "gets": "←",
    "leftrightarrow": "↔",
    "Rightarrow": "⇒",
    "Leftarrow": "⇐",
    "Leftrightarrow": "⇔",
    "iff": "⇔",
    "mapsto": "↦",
    "partial": "∂",
    "nabla": "∇",
    "infty": "∞",
    "forall": "∀",
    "exists": "∃",
    "neg": "¬",
    "angle": "∠",
    "hbar": "ℏ",
    "ell": "ℓ",
    "dots": "…",
    "ldots": "…",
    "cdots": "⋯",
    "vdots": "⋮",
    "ddots": "⋱",
    "prime": "′",
    "Re": "ℜ",
    "Im": "ℑ",
    "vert": "|",
    "Vert": "‖",
    "langle": "⟨",
    "rangle": "⟩",
    "lfloor": "⌊",
    "rfloor": "⌋",
    "lceil": "⌈",
    "rceil": "⌉",
}

# N-ary operators
NARY_OPS: dict[str, str] = {
    "int": "∫",
    "iint": "∬",
    "iiint": "∭",
    "oint": "∮",
    "sum": "∑",
    "prod": "∏",
    "coprod": "∐",
    "bigcap": "⋂",
    "bigcup": "⋃",
}

# Standard function names
MATH_FUNCTIONS: frozenset[str] = frozenset(
    {
        "sin",
        "cos",
        "tan",
        "cot",
        "sec",
        "csc",
        "arcsin",
        "arccos",
        "arctan",
        "sinh",
        "cosh",
        "tanh",
        "coth",
        "ln",
        "log",
        "exp",
        "det",
        "dim",
        "deg",
        "gcd",
        "hom",
        "ker",
        "arg",
        "min",
        "max",
        "sup",
        "inf",
        "lim",
        "liminf",
        "limsup",
    }
)

# Accents mapping
MATH_ACCENTS: dict[str, str] = {
    "dot": "˙",
    "ddot": "¨",
    "dddot": "⃛",
    "bar": "¯",
    "overline": "¯",
    "hat": "^",
    "tilde": "~",
    "vec": "→",
}

# Spaces mapping
MATH_SPACES: dict[str, str] = {
    ",": "0.167em",
    ":": "0.222em",
    ";": "0.278em",
    "quad": "1em",
    "qquad": "2em",
    " ": "0.25em",
}

# Matrix environment boundary delimiters: (open, close)
MATRIX_FENCES: dict[str, tuple[str, str]] = {
    "matrix": ("", ""),
    "pmatrix": ("(", ")"),
    "bmatrix": ("[", "]"),
    "Bmatrix": ("{", "}"),
    "vmatrix": ("|", "|"),
    "Vmatrix": ("‖", "‖"),
    "cases": ("{", ""),
    "aligned": ("", ""),
    "align": ("", ""),
    "align*": ("", ""),
    "split": ("", ""),
}

DELIMITER_MAP: dict[str, str] = {
    "(": "(",
    ")": ")",
    "[": "[",
    "]": "]",
    "\\{": "{",
    "\\}": "}",
    "{": "{",
    "}": "}",
    "|": "|",
    "\\vert": "|",
    "\\|": "‖",
    "\\Vert": "‖",
    "\\langle": "⟨",
    "\\rangle": "⟩",
    "\\lfloor": "⌊",
    "\\rfloor": "⌋",
    "\\lceil": "⌈",
    "\\rceil": "⌉",
    ".": "",
}


def _clean_latex_input(latex: str) -> str:
    """Strip mathematical wrappers and outer whitespace."""
    s = latex.strip()
    if not s:
        raise EquationConversionError("LaTeX string cannot be empty")

    # Strip $$...$$ or $...$
    while s.startswith("$$") and s.endswith("$$") and len(s) >= 4:
        s = s[2:-2].strip()
    while s.startswith("$") and s.endswith("$") and len(s) >= 2:
        s = s[1:-1].strip()

    # Strip \[...\] or \(...\)
    if (s.startswith("\\[") and s.endswith("\\]")) or (
        s.startswith("\\(") and s.endswith("\\)")
    ):
        s = s[2:-2].strip()

    # Strip \begin{equation}...\end{equation}
    eq_match = re.match(
        r"^\\begin\{equation\*?\}(.*?)\\end\{equation\*?\}$", s, re.DOTALL
    )
    if eq_match:
        s = eq_match.group(1).strip()

    if not s:
        raise EquationConversionError("LaTeX string cannot be empty")
    return s


class Token:
    def __init__(self, kind: str, value: str, pos: int = 0) -> None:
        self.kind = kind
        self.value = value
        self.pos = pos

    def __repr__(self) -> str:
        return f"Token({self.kind!r}, {self.value!r})"


class Tokenizer:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0
        self.length = len(text)

    def next_token(self) -> Token | None:
        # Skip whitespace in normal mode
        while self.pos < self.length and self.text[self.pos].isspace():
            self.pos += 1

        if self.pos >= self.length:
            return None

        start = self.pos
        ch = self.text[self.pos]

        if ch == "\\":
            self.pos += 1
            if self.pos >= self.length:
                return Token("CHAR", "\\", start)
            next_ch = self.text[self.pos]
            if next_ch.isalpha():
                cmd_start = self.pos
                while self.pos < self.length and self.text[self.pos].isalpha():
                    self.pos += 1
                cmd = self.text[cmd_start : self.pos]
                return Token("COMMAND", cmd, start)
            elif next_ch in "\\%&_{}#~,:; ":
                self.pos += 1
                return Token("ESC_CHAR", next_ch, start)
            else:
                self.pos += 1
                return Token("ESC_CHAR", next_ch, start)

        if ch.isdigit():
            num_start = self.pos
            while self.pos < self.length and self.text[self.pos].isdigit():
                self.pos += 1
            if self.pos < self.length and self.text[self.pos] == ".":
                self.pos += 1
                while self.pos < self.length and self.text[self.pos].isdigit():
                    self.pos += 1
            return Token("NUMBER", self.text[num_start : self.pos], start)

        if ch.isalpha():
            self.pos += 1
            return Token("LETTER", ch, start)

        self.pos += 1
        return Token("CHAR", ch, start)

    def tokenize_all(self) -> list[Token]:
        tokens: list[Token] = []
        while True:
            tok = self.next_token()
            if tok is None:
                break
            tokens.append(tok)
        return tokens


class LaTeXParser:
    """Recursive-descent parser building Presentation MathML elements."""

    def __init__(self, tokens: list[Token], raw_latex: str = "") -> None:
        self.tokens = tokens
        self.raw_latex = raw_latex
        self.pos = 0
        self.length = len(tokens)

    def peek(self) -> Token | None:
        if self.pos < self.length:
            return self.tokens[self.pos]
        return None

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def match(self, kind: str, value: str | None = None) -> bool:
        tok = self.peek()
        if tok is None:
            return False
        if tok.kind != kind:
            return False
        return not (value is not None and tok.value != value)

    def consume(self, kind: str, value: str | None = None) -> Token:
        if not self.match(kind, value):
            expected = f"{kind}({value!r})" if value is not None else kind
            got = self.peek()
            raise EquationConversionError(
                f"expected token {expected}, got {got!r} near pos {getattr(got, 'pos', self.pos)}"
            )
        return self.advance()

    def parse_math(self) -> ET.Element:
        """Parse all tokens into a MathML <math> root element."""
        math = ET.Element(f"{{{MATHML_NS}}}math")
        elements = self.parse_sequence()
        if len(elements) == 1 and elements[0].tag == f"{{{MATHML_NS}}}mrow":
            math.extend(list(elements[0]))
        else:
            math.extend(elements)
        return math

    def parse_sequence(
        self, stop_tokens: set[tuple[str, str]] | None = None
    ) -> list[ET.Element]:
        """Parse a sequence of math expressions until end or a stop token."""
        elems: list[ET.Element] = []
        while self.pos < self.length:
            tok = self.peek()
            if tok is None:
                break
            if stop_tokens and (tok.kind, tok.value) in stop_tokens:
                break
            # Group closer stop check
            if tok.kind == "CHAR" and tok.value in "}&":
                break
            if tok.kind == "ESC_CHAR" and tok.value == "\\":
                break

            parsed = self.parse_expression()
            if parsed is not None:
                elems.append(parsed)

        return elems

    def parse_argument(self) -> list[ET.Element]:
        """Parse a required argument: either {sequence} or a single atom."""
        tok = self.peek()
        if tok is None:
            raise EquationConversionError(
                "unexpected end of expression while parsing argument"
            )

        if tok.kind == "CHAR" and tok.value == "{":
            self.advance()  # consume {
            elems = self.parse_sequence()
            self.consume("CHAR", "}")
            return elems

        # Single atom argument
        atom = self.parse_atom()
        return [atom] if atom is not None else []

    def parse_optional_bracket_arg(self) -> list[ET.Element] | None:
        """Parse an optional bracket argument: [sequence]."""
        tok = self.peek()
        if tok is not None and tok.kind == "CHAR" and tok.value == "[":
            self.advance()  # consume [
            elems = self.parse_sequence(stop_tokens={("CHAR", "]")})
            self.consume("CHAR", "]")
            return elems
        return None

    def parse_expression(self) -> ET.Element | None:
        """Parse an expression: atom followed by optional sub/superscripts."""
        base = self.parse_atom()
        if base is None:
            return None

        # Check for subscript / superscript / primes
        sub: list[ET.Element] | None = None
        sup: list[ET.Element] | None = None

        while self.pos < self.length:
            tok = self.peek()
            if tok is None:
                break

            if tok.kind == "CHAR" and tok.value == "_":
                self.advance()  # consume _
                sub = self.parse_argument()
            elif tok.kind == "CHAR" and tok.value == "^":
                self.advance()  # consume ^
                sup = self.parse_argument()
            elif tok.kind == "CHAR" and tok.value == "'":
                self.advance()  # consume '
                prime_mo = ET.Element(f"{{{MATHML_NS}}}mo")
                prime_mo.text = "′"
                sup = [prime_mo]
            else:
                break

        if sub is not None and sup is not None:
            subsup = ET.Element(f"{{{MATHML_NS}}}msubsup")
            subsup.append(base)
            subsup.append(self._wrap_in_mrow(sub))
            subsup.append(self._wrap_in_mrow(sup))
            return subsup
        elif sub is not None:
            msub = ET.Element(f"{{{MATHML_NS}}}msub")
            msub.append(base)
            msub.append(self._wrap_in_mrow(sub))
            return msub
        elif sup is not None:
            msup = ET.Element(f"{{{MATHML_NS}}}msup")
            msup.append(base)
            msup.append(self._wrap_in_mrow(sup))
            return msup

        return base

    def parse_atom(self) -> ET.Element | None:
        tok = self.peek()
        if tok is None:
            return None

        # Group: { ... }
        if tok.kind == "CHAR" and tok.value == "{":
            self.advance()
            inner = self.parse_sequence()
            self.consume("CHAR", "}")
            return self._wrap_in_mrow(inner)

        # Numbers
        if tok.kind == "NUMBER":
            self.advance()
            mn = ET.Element(f"{{{MATHML_NS}}}mn")
            mn.text = tok.value
            return mn

        # Letters (Variables)
        if tok.kind == "LETTER":
            self.advance()
            mi = ET.Element(f"{{{MATHML_NS}}}mi")
            mi.text = tok.value
            return mi

        # Commands
        if tok.kind == "COMMAND":
            return self.parse_command()

        # Escaped characters
        if tok.kind == "ESC_CHAR":
            self.advance()
            val = tok.value
            if val in MATH_SPACES:
                mspace = ET.Element(f"{{{MATHML_NS}}}mspace")
                mspace.set("width", MATH_SPACES[val])
                return mspace
            mo = ET.Element(f"{{{MATHML_NS}}}mo")
            mo.text = val
            return mo

        # Operators & punctuation
        if tok.kind == "CHAR":
            ch = tok.value
            if ch in "+-*/=<>!?:,|()[]~":
                self.advance()
                mo = ET.Element(f"{{{MATHML_NS}}}mo")
                mo.text = ch
                return mo

            # Unhandled character
            self.advance()
            mo = ET.Element(f"{{{MATHML_NS}}}mo")
            mo.text = ch
            return mo

        return None

    def parse_command(self) -> ET.Element:
        tok = self.advance()
        cmd = tok.value

        # Greek letters
        if cmd in GREEK_LETTERS:
            mi = ET.Element(f"{{{MATHML_NS}}}mi")
            mi.text = GREEK_LETTERS[cmd]
            return mi

        # Math symbols
        if cmd in MATH_SYMBOLS:
            mo = ET.Element(f"{{{MATHML_NS}}}mo")
            mo.text = MATH_SYMBOLS[cmd]
            return mo

        # N-ary operators
        if cmd in NARY_OPS:
            mo = ET.Element(f"{{{MATHML_NS}}}mo")
            mo.text = NARY_OPS[cmd]
            return mo

        # Math functions
        if cmd in MATH_FUNCTIONS:
            mi = ET.Element(f"{{{MATHML_NS}}}mi")
            mi.set("mathvariant", "normal")
            mi.text = cmd
            return mi

        # Fractions: \frac, \dfrac, \tfrac
        if cmd in ("frac", "dfrac", "tfrac"):
            num = self.parse_argument()
            den = self.parse_argument()
            mfrac = ET.Element(f"{{{MATHML_NS}}}mfrac")
            mfrac.append(self._wrap_in_mrow(num))
            mfrac.append(self._wrap_in_mrow(den))
            return mfrac

        # Roots: \sqrt
        if cmd == "sqrt":
            deg = self.parse_optional_bracket_arg()
            radicand = self.parse_argument()
            if deg is not None:
                mroot = ET.Element(f"{{{MATHML_NS}}}mroot")
                mroot.append(self._wrap_in_mrow(radicand))
                mroot.append(self._wrap_in_mrow(deg))
                return mroot
            else:
                msqrt = ET.Element(f"{{{MATHML_NS}}}msqrt")
                msqrt.append(self._wrap_in_mrow(radicand))
                return msqrt

        # Accents
        if cmd in MATH_ACCENTS:
            accent_chr = MATH_ACCENTS[cmd]
            base = self.parse_argument()
            mover = ET.Element(f"{{{MATHML_NS}}}mover")
            mover.set("accent", "true")
            mover.append(self._wrap_in_mrow(base))
            mo = ET.Element(f"{{{MATHML_NS}}}mo")
            mo.text = accent_chr
            mover.append(mo)
            return mover

        # Font formatting: \mathrm, \mathbf, \mathit, \text, \operatorname
        if cmd in (
            "mathrm",
            "mathbf",
            "mathit",
            "mathtt",
            "mathbb",
            "mathcal",
            "text",
            "operatorname",
        ):
            variant_map = {
                "mathrm": "normal",
                "text": "normal",
                "operatorname": "normal",
                "mathbf": "bold",
                "mathit": "italic",
                "mathtt": "monospace",
                "mathbb": "double-struck",
                "mathcal": "script",
            }
            variant = variant_map.get(cmd, "normal")
            arg_elems = self.parse_argument()
            # If text, we can join texts into an mtext or mi
            mrow = ET.Element(f"{{{MATHML_NS}}}mrow")
            for elem in arg_elems:
                if elem.tag in (f"{{{MATHML_NS}}}mi", f"{{{MATHML_NS}}}mn"):
                    elem.set("mathvariant", variant)
                mrow.append(elem)
            return mrow

        # Spacing commands
        if cmd in MATH_SPACES:
            mspace = ET.Element(f"{{{MATHML_NS}}}mspace")
            mspace.set("width", MATH_SPACES[cmd])
            return mspace

        # Delimiters: \left ... \right
        if cmd == "left":
            return self.parse_left_right()

        # Environments: \begin ... \end
        if cmd == "begin":
            return self.parse_environment()

        # Style switches that can be safely ignored or mapped
        if cmd in ("displaystyle", "textstyle", "scriptstyle", "scriptscriptstyle"):
            # No-op in mathml structure
            empty = ET.Element(f"{{{MATHML_NS}}}mrow")
            return empty

        # If unknown macro: raise UnsupportedMacroError
        raise UnsupportedMacroError(cmd, f"unsupported LaTeX macro: \\{cmd}")

    def parse_left_right(self) -> ET.Element:
        """Parse \\left <delim> ... \\right <delim> into an <mfenced> or <mrow>."""
        open_delim = self._read_delimiter()

        content = self.parse_sequence(stop_tokens={("COMMAND", "right")})

        if not self.match("COMMAND", "right"):
            raise EquationConversionError("missing \\right to close \\left")
        self.advance()  # consume \right
        close_delim = self._read_delimiter()

        mfenced = ET.Element(f"{{{MATHML_NS}}}mfenced")
        mfenced.set("open", open_delim)
        mfenced.set("close", close_delim)
        mfenced.set("separators", "")
        mfenced.append(self._wrap_in_mrow(content))
        return mfenced

    def _read_delimiter(self) -> str:
        tok = self.peek()
        if tok is None:
            raise EquationConversionError("expected delimiter after \\left or \\right")

        self.advance()
        if tok.kind in ("COMMAND", "ESC_CHAR"):
            key = f"\\{tok.value}"
            return DELIMITER_MAP.get(key, tok.value)
        elif tok.kind == "CHAR":
            return DELIMITER_MAP.get(tok.value, tok.value)
        return tok.value

    def parse_environment(self) -> ET.Element:
        """Parse \\begin{env} ... \\end{env}."""
        # Read environment name from {env}
        env_tokens = self.parse_argument()
        env_name = "".join(e.text or "" for e in env_tokens)

        if env_name not in MATRIX_FENCES:
            raise UnsupportedMacroError(
                env_name, f"unsupported LaTeX environment: \\begin{{{env_name}}}"
            )

        open_fence, close_fence = MATRIX_FENCES[env_name]

        # Parse table rows and cells until \end{env_name}
        rows: list[list[list[ET.Element]]] = []
        current_row: list[list[ET.Element]] = []
        current_cell: list[ET.Element] = []

        while self.pos < self.length:
            tok = self.peek()
            if tok is None:
                break

            if tok.kind == "COMMAND" and tok.value == "end":
                self.advance()  # consume \end
                end_tokens = self.parse_argument()
                end_name = "".join(e.text or "" for e in end_tokens)
                if end_name != env_name:
                    raise EquationConversionError(
                        f"mismatched environment: \\begin{{{env_name}}} ended with \\end{{{end_name}}}"
                    )
                # End of environment
                current_row.append(current_cell)
                rows.append(current_row)
                break

            if tok.kind == "CHAR" and tok.value == "&":
                self.advance()  # consume &
                current_row.append(current_cell)
                current_cell = []
                continue

            if tok.kind == "ESC_CHAR" and tok.value == "\\":
                self.advance()  # consume \\
                # Skip optional [dim] row spacing
                self.parse_optional_bracket_arg()
                current_row.append(current_cell)
                rows.append(current_row)
                current_row = []
                current_cell = []
                continue

            elem = self.parse_expression()
            if elem is not None:
                current_cell.append(elem)

        mtable = ET.Element(f"{{{MATHML_NS}}}mtable")
        for row in rows:
            # Skip empty trailing rows if cell is empty and row is empty
            if len(row) == 1 and not row[0] and row == rows[-1]:
                continue
            mtr = ET.SubElement(mtable, f"{{{MATHML_NS}}}mtr")
            for cell in row:
                mtd = ET.SubElement(mtr, f"{{{MATHML_NS}}}mtd")
                mtd.append(self._wrap_in_mrow(cell))

        if open_fence or close_fence:
            mfenced = ET.Element(f"{{{MATHML_NS}}}mfenced")
            mfenced.set("open", open_fence)
            mfenced.set("close", close_fence)
            mfenced.append(mtable)
            return mfenced

        return mtable

    def _wrap_in_mrow(self, elems: list[ET.Element]) -> ET.Element:
        if len(elems) == 1 and elems[0].tag == f"{{{MATHML_NS}}}mrow":
            return elems[0]
        mrow = ET.Element(f"{{{MATHML_NS}}}mrow")
        mrow.extend(elems)
        return mrow


def latex_to_mathml(latex: str) -> str:
    """Convert a LaTeX mathematical expression string into W3C Presentation MathML XML string.

    Args:
        latex: Standard LaTeX mathematical expression (e.g. 'E = mc^2' or r'\\frac{1}{s}').

    Returns:
        XML string of the Presentation MathML (<math> root).

    Raises:
        UnsupportedMacroError: If the expression contains complex/unsupported macros.
        EquationConversionError: If parsing or conversion fails.
    """
    cleaned = _clean_latex_input(latex)
    tokenizer = Tokenizer(cleaned)
    tokens = tokenizer.tokenize_all()
    parser = LaTeXParser(tokens, raw_latex=cleaned)
    math_elem = parser.parse_math()
    return ET.tostring(math_elem, encoding="unicode")
