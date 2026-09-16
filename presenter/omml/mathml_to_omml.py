"""Convert W3C Presentation MathML to Office Math Markup Language (OMML)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from presenter.omml.errors import EquationConversionError

MATHML_NS = "http://www.w3.org/1998/Math/MathML"
OMML_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"

ET.register_namespace("m", OMML_NS)

NARY_SYMBOLS = frozenset({"∫", "∬", "∭", "∮", "∑", "∏", "∐", "⋂", "⋃"})


def _strip_ns(tag: str) -> str:
    """Return local tag name without namespace prefix."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


class MathMLToOMMLConverter:
    """Translates a Presentation MathML ElementTree into an OMML ElementTree."""

    def __init__(self) -> None:
        self._m = lambda tag: f"{{{OMML_NS}}}{tag}"

    def convert_math(self, root: ET.Element) -> ET.Element:
        """Convert a MathML <math> root element into an <m:oMath> element."""
        tag = _strip_ns(root.tag)
        if tag != "math":
            raise EquationConversionError(f"expected MathML <math> root, got <{tag}>")

        omath = ET.Element(self._m("oMath"))
        for child in root:
            self._convert_and_append(child, omath)
        return omath

    def _convert_and_append(self, src: ET.Element, target: ET.Element) -> None:
        """Convert MathML element `src` and append resulting OMML element(s) to `target`."""
        tag = _strip_ns(src.tag)

        if tag == "mrow":
            for child in src:
                self._convert_and_append(child, target)

        elif tag in ("mi", "mn", "mo", "mtext"):
            r = self._convert_token(src)
            if r is not None:
                target.append(r)

        elif tag == "mspace":
            r = ET.Element(self._m("r"))
            t = ET.SubElement(r, self._m("t"))
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            t.text = " "
            target.append(r)

        elif tag == "mfrac":
            f = self._convert_frac(src)
            target.append(f)

        elif tag == "msqrt":
            rad = self._convert_sqrt(src)
            target.append(rad)

        elif tag == "mroot":
            rad = self._convert_mroot(src)
            target.append(rad)

        elif tag == "msub":
            sub = self._convert_sub(src)
            target.append(sub)

        elif tag == "msup":
            sup = self._convert_sup(src)
            target.append(sup)

        elif tag == "msubsup":
            subsup = self._convert_subsup(src)
            target.append(subsup)

        elif tag == "mfenced":
            d = self._convert_fenced(src)
            target.append(d)

        elif tag == "mtable":
            m = self._convert_table(src)
            target.append(m)

        elif tag == "mover":
            acc = self._convert_mover(src)
            target.append(acc)

        elif tag == "munder":
            lim = self._convert_munder(src)
            target.append(lim)

        elif tag == "munderover":
            nary = self._convert_munderover(src)
            target.append(nary)

        else:
            # Fallback: process children into target
            for child in src:
                self._convert_and_append(child, target)

    def _convert_token(self, src: ET.Element) -> ET.Element | None:
        text = src.text or ""
        if not text and not len(src):
            return None

        tag = _strip_ns(src.tag)
        variant = src.get("mathvariant")

        r = ET.Element(self._m("r"))

        # Check font variant property
        if variant == "normal" or tag == "mtext":
            rPr = ET.SubElement(r, self._m("rPr"))
            sty = ET.SubElement(rPr, self._m("sty"))
            sty.set(self._m("val"), "p")
        elif variant == "bold":
            rPr = ET.SubElement(r, self._m("rPr"))
            sty = ET.SubElement(rPr, self._m("sty"))
            sty.set(self._m("val"), "b")
        elif variant == "italic":
            rPr = ET.SubElement(r, self._m("rPr"))
            sty = ET.SubElement(rPr, self._m("sty"))
            sty.set(self._m("val"), "i")
        elif variant == "bold-italic":
            rPr = ET.SubElement(r, self._m("rPr"))
            sty = ET.SubElement(rPr, self._m("sty"))
            sty.set(self._m("val"), "bi")

        t = ET.SubElement(r, self._m("t"))
        if text.startswith(" ") or text.endswith(" "):
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = text
        return r

    def _convert_frac(self, src: ET.Element) -> ET.Element:
        children = list(src)
        if len(children) < 2:
            raise EquationConversionError("<mfrac> requires at least 2 child elements")

        f = ET.Element(self._m("f"))
        num = ET.SubElement(f, self._m("num"))
        self._convert_and_append(children[0], num)

        den = ET.SubElement(f, self._m("den"))
        self._convert_and_append(children[1], den)
        return f

    def _convert_sqrt(self, src: ET.Element) -> ET.Element:
        rad = ET.Element(self._m("rad"))
        radPr = ET.SubElement(rad, self._m("radPr"))
        degHide = ET.SubElement(radPr, self._m("degHide"))
        degHide.set(self._m("val"), "1")
        ET.SubElement(rad, self._m("deg"))

        e = ET.SubElement(rad, self._m("e"))
        for child in src:
            self._convert_and_append(child, e)
        return rad

    def _convert_mroot(self, src: ET.Element) -> ET.Element:
        children = list(src)
        if len(children) < 2:
            raise EquationConversionError("<mroot> requires 2 child elements")

        rad = ET.Element(self._m("rad"))
        deg = ET.SubElement(rad, self._m("deg"))
        self._convert_and_append(children[1], deg)

        e = ET.SubElement(rad, self._m("e"))
        self._convert_and_append(children[0], e)
        return rad

    def _convert_sub(self, src: ET.Element) -> ET.Element:
        children = list(src)
        if len(children) < 2:
            raise EquationConversionError("<msub> requires 2 child elements")

        sSub = ET.Element(self._m("sSub"))
        e = ET.SubElement(sSub, self._m("e"))
        self._convert_and_append(children[0], e)

        sub = ET.SubElement(sSub, self._m("sub"))
        self._convert_and_append(children[1], sub)
        return sSub

    def _convert_sup(self, src: ET.Element) -> ET.Element:
        children = list(src)
        if len(children) < 2:
            raise EquationConversionError("<msup> requires 2 child elements")

        sSup = ET.Element(self._m("sSup"))
        e = ET.SubElement(sSup, self._m("e"))
        self._convert_and_append(children[0], e)

        sup = ET.SubElement(sSup, self._m("sup"))
        self._convert_and_append(children[1], sup)
        return sSup

    def _convert_subsup(self, src: ET.Element) -> ET.Element:
        children = list(src)
        if len(children) < 3:
            raise EquationConversionError("<msubsup> requires 3 child elements")

        base = children[0]
        base_text = (base.text or "").strip()

        # Check if base is an n-ary operator (like \int or \sum)
        if _strip_ns(base.tag) == "mo" and base_text in NARY_SYMBOLS:
            nary = ET.Element(self._m("nary"))
            naryPr = ET.SubElement(nary, self._m("naryPr"))
            chr_elem = ET.SubElement(naryPr, self._m("chr"))
            chr_elem.set(self._m("val"), base_text)

            sub = ET.SubElement(nary, self._m("sub"))
            self._convert_and_append(children[1], sub)

            sup = ET.SubElement(nary, self._m("sup"))
            self._convert_and_append(children[2], sup)

            ET.SubElement(nary, self._m("e"))
            return nary

        sSubSup = ET.Element(self._m("sSubSup"))
        e = ET.SubElement(sSubSup, self._m("e"))
        self._convert_and_append(base, e)

        sub = ET.SubElement(sSubSup, self._m("sub"))
        self._convert_and_append(children[1], sub)

        sup = ET.SubElement(sSubSup, self._m("sup"))
        self._convert_and_append(children[2], sup)
        return sSubSup

    def _convert_fenced(self, src: ET.Element) -> ET.Element:
        open_chr = src.get("open", "(")
        close_chr = src.get("close", ")")

        d = ET.Element(self._m("d"))
        dPr = ET.SubElement(d, self._m("dPr"))
        if open_chr:
            begChr = ET.SubElement(dPr, self._m("begChr"))
            begChr.set(self._m("val"), open_chr)
        if close_chr:
            endChr = ET.SubElement(dPr, self._m("endChr"))
            endChr.set(self._m("val"), close_chr)
        grow = ET.SubElement(dPr, self._m("grow"))
        grow.set(self._m("val"), "1")

        e = ET.SubElement(d, self._m("e"))
        for child in src:
            self._convert_and_append(child, e)
        return d

    def _convert_table(self, src: ET.Element) -> ET.Element:
        m = ET.Element(self._m("m"))
        mPr = ET.SubElement(m, self._m("mPr"))
        baseJc = ET.SubElement(mPr, self._m("baseJc"))
        baseJc.set(self._m("val"), "center")
        rSp = ET.SubElement(mPr, self._m("rSp"))
        rSp.set(self._m("val"), "0")
        cSp = ET.SubElement(mPr, self._m("cSp"))
        cSp.set(self._m("val"), "0")

        for row in src:
            if _strip_ns(row.tag) != "mtr":
                continue
            mr = ET.SubElement(m, self._m("mr"))
            for cell in row:
                if _strip_ns(cell.tag) != "mtd":
                    continue
                e = ET.SubElement(mr, self._m("e"))
                for child in cell:
                    self._convert_and_append(child, e)
        return m

    def _convert_mover(self, src: ET.Element) -> ET.Element:
        children = list(src)
        if len(children) < 2:
            raise EquationConversionError("<mover> requires 2 child elements")

        accent_chr = (children[1].text or "").strip()
        is_accent = src.get("accent") == "true" or accent_chr in (
            "˙",
            "¨",
            "⃛",
            "¯",
            "^",
            "~",
            "→",
        )

        if is_accent:
            acc = ET.Element(self._m("acc"))
            accPr = ET.SubElement(acc, self._m("accPr"))
            chr_elem = ET.SubElement(accPr, self._m("chr"))
            chr_elem.set(self._m("val"), accent_chr or "˙")

            e = ET.SubElement(acc, self._m("e"))
            self._convert_and_append(children[0], e)
            return acc

        limUpp = ET.Element(self._m("limUpp"))
        e = ET.SubElement(limUpp, self._m("e"))
        self._convert_and_append(children[0], e)
        lim = ET.SubElement(limUpp, self._m("lim"))
        self._convert_and_append(children[1], lim)
        return lim

    def _convert_munder(self, src: ET.Element) -> ET.Element:
        children = list(src)
        if len(children) < 2:
            raise EquationConversionError("<munder> requires 2 child elements")

        limLow = ET.Element(self._m("limLow"))
        e = ET.SubElement(limLow, self._m("e"))
        self._convert_and_append(children[0], e)
        lim = ET.SubElement(limLow, self._m("lim"))
        self._convert_and_append(children[1], lim)
        return lim

    def _convert_munderover(self, src: ET.Element) -> ET.Element:
        children = list(src)
        if len(children) < 3:
            raise EquationConversionError("<munderover> requires 3 child elements")

        base = children[0]
        base_text = (base.text or "").strip()

        if _strip_ns(base.tag) == "mo" and base_text in NARY_SYMBOLS:
            nary = ET.Element(self._m("nary"))
            naryPr = ET.SubElement(nary, self._m("naryPr"))
            chr_elem = ET.SubElement(naryPr, self._m("chr"))
            chr_elem.set(self._m("val"), base_text)
            limLoc = ET.SubElement(naryPr, self._m("limLoc"))
            limLoc.set(self._m("val"), "undOvr")

            sub = ET.SubElement(nary, self._m("sub"))
            self._convert_and_append(children[1], sub)

            sup = ET.SubElement(nary, self._m("sup"))
            self._convert_and_append(children[2], sup)

            ET.SubElement(nary, self._m("e"))
            return nary

        sSubSup = ET.Element(self._m("sSubSup"))
        e = ET.SubElement(sSubSup, self._m("e"))
        self._convert_and_append(base, e)

        sub = ET.SubElement(sSubSup, self._m("sub"))
        self._convert_and_append(children[1], sub)

        sup = ET.SubElement(sSubSup, self._m("sup"))
        self._convert_and_append(children[2], sup)
        return sSubSup


def mathml_to_omml(mathml_xml: str | ET.Element) -> str:
    """Convert a W3C Presentation MathML XML string or Element to an OMML (<m:oMath>) XML string.

    Args:
        mathml_xml: MathML XML string (<math> root) or ElementTree Element.

    Returns:
        XML string of the OMML (<m:oMath> root).
    """
    if isinstance(mathml_xml, str):
        root = ET.fromstring(mathml_xml)
    else:
        root = mathml_xml

    converter = MathMLToOMMLConverter()
    omml_elem = converter.convert_math(root)
    return ET.tostring(omml_elem, encoding="unicode")
