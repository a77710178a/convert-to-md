"""Math extraction helpers: MathML / LaTeX / OMML → markdown-friendly LaTeX."""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET


_TEX_ENC = re.compile(r"(?i)(application/x-tex|text/x-tex|latex|tex)")


def clean_latex(tex: str) -> str:
    tex = (tex or "").strip()
    # unwrap {\displaystyle ...} / {\textstyle ...}
    for _ in range(3):
        m = re.match(r"^\{?\\(displaystyle|textstyle|scriptstyle)\s+(.*)\}?\s*$", tex, flags=re.S)
        if m:
            tex = m.group(2).strip()
            if tex.endswith("}") and tex.count("{") < tex.count("}"):
                tex = tex[:-1].strip()
            continue
        m = re.match(r"^\\(displaystyle|textstyle|scriptstyle)\s+(.*)$", tex, flags=re.S)
        if m:
            tex = m.group(2).strip()
            continue
        break
    tex = re.sub(r"^\\(displaystyle|textstyle|scriptstyle)\s*", "", tex)

    # unwrap a single outer brace group when it wraps an environment
    if tex.startswith("{\\begin{") and tex.endswith("}"):
        inner = tex[1:-1].strip()
        if inner.startswith("\\begin{") and "\\end{" in inner:
            tex = inner

    # drop \vphantom{...} (MathJax often inserts a space: \vphantom {|})
    for _ in range(6):
        nxt = re.sub(r"\\vphantom\s*\{[^{}]*\}", "", tex)
        nxt = re.sub(r"\{\s*\}", "", nxt)
        if nxt == tex:
            break
        tex = nxt

    # normalize spacing tokens (not \\ newlines)
    tex = re.sub(r"(?<!\\)\\[,;:!]", " ", tex)
    tex = re.sub(r"\\quad|\\qquad", " ", tex)
    tex = re.sub(r"[ \t]{2,}", " ", tex)
    return tex.strip()


def pretty_latex(tex: str) -> str:
    """Make multi-line environments readable without changing math meaning much."""
    tex = clean_latex(tex)
    if not tex:
        return ""

    # Escape raw $ inside math so markdown $$ fences stay intact.
    tex = tex.replace("\\$", "§ESCAPED_DOLLAR§")
    tex = tex.replace("$", "\\$")
    tex = tex.replace("§ESCAPED_DOLLAR§", "\\$")

    def _break_rows(body: str) -> str:
        # Match LaTeX row breaks: \\ or \\[2pt] / \\[3mu]
        out: list[str] = []
        i = 0
        n = len(body)
        while i < n:
            if body[i] == "\\" and i + 1 < n and body[i + 1] == "\\":
                j = i + 2
                if j < n and body[j] == "[":
                    k = body.find("]", j + 1)
                    if k != -1:
                        j = k + 1
                out.append("\\\\\n")
                i = j
                # skip following whitespace/newlines to avoid blank rows
                while i < n and body[i] in " \t\r\n":
                    i += 1
                continue
            out.append(body[i])
            i += 1
        body = "".join(out)
        body = re.sub(r"(?:\\\\\n){2,}", "\\\\\n", body)
        return body.strip()

    def _env_repl(match: re.Match[str]) -> str:
        name = match.group(1)
        opt = match.group(2) or ""
        opt = re.sub(r"^\[\]", "", opt)  # drop empty [] from LaTeXML array
        body = _break_rows(match.group(3))
        return f"\\begin{{{name}}}{opt}\n{body}\n\\end{{{name}}}"

    tex = re.sub(
        r"\\begin\{(aligned|align\*?|array|cases|matrix|pmatrix|bmatrix|vmatrix|Vmatrix|gather\*?|multline\*?|split)\}((?:\[[^\]]*\])?(?:\{[^}]*\})?)\s*(.*?)\\end\{\1\}",
        _env_repl,
        tex,
        flags=re.S,
    )

    # unwrap pure outer braces around a full environment only
    m = re.match(r"^\{(\\begin\{[a-zA-Z]+\*?\}[\s\S]*\\end\{[a-zA-Z]+\*?\})\}$", tex)
    if m:
        tex = m.group(1).strip()

    tex = re.sub(r"[ \t]*\n[ \t]*", "\n", tex)
    tex = re.sub(r"\n{3,}", "\n\n", tex)
    return tex.strip()


def latex_to_markdown(tex: str, *, display: bool = False) -> str:
    tex = pretty_latex(tex)
    if not tex:
        return ""
    # force display for multi-line environments even if source said inline
    if not display and re.search(r"\\begin\{(aligned|align\*?|array|cases|matrix|pmatrix|bmatrix)\}", tex):
        display = True
    if display:
        return f"$$\n{tex}\n$$"
    if tex.startswith("$$") or (tex.startswith("$") and not tex.startswith("\\$")):
        return tex
    return f"${tex}$"


def extract_latex_from_math_element(math_el) -> tuple[str, bool, str | None]:
    """Return (latex, display, equation_number) from a BeautifulSoup <math> element."""
    disp = (math_el.get("display") or "").lower()
    display = disp == "block"
    alt = math_el.get("alttext") or math_el.get("altText") or ""

    # Only promote when the math sits in a clear display container, not every
    # equation-table row (ar5iv puts many inline fragments inside ltx_equation rows).
    if not display:
        for parent in math_el.parents:
            if not getattr(parent, "name", None):
                continue
            classes = " ".join(parent.get("class") or [])
            if re.search(r"(?i)\b(ltx_eqn_display|MathJax_Display|display-math|display_equation)\b", classes):
                display = True
                break
            if parent.name in {"body", "html"}:
                break
        # sole child of a paragraph-like block and marked displaystyle in alttext
        if not display and math_el.parent is not None:
            parent = math_el.parent
            if parent.name in {"p", "div", "td", "span"}:
                nontrivial = [
                    s
                    for s in parent.find_all(string=True)
                    if str(s).strip() and not str(s).strip().isdigit()
                ]
                if len(nontrivial) <= 1 and "displaystyle" in (alt or ""):
                    display = True

    latex = ""
    for ann in math_el.find_all("annotation"):
        enc = ann.get("encoding") or ""
        if _TEX_ENC.search(enc):
            latex = ann.get_text() or ""
            break
    if not latex and alt:
        latex = alt
    if not latex:
        latex = mathml_to_latex_approx(math_el)

    latex = clean_latex(latex)
    # light cleanup of common noisy macros for readability
    latex = re.sub(r"\\mathop\{\\mbox\{\\rm\s+([^}]+)\}\}", r"\\mathrm{\1}", latex)
    latex = re.sub(r"\\mathop\{\\mbox\{\\bf\s+([^}]+)\}\}", r"\\mathbf{\1}", latex)
    latex = re.sub(r"\\mbox\{\\rm\s+([^}]+)\}", r"\\mathrm{\1}", latex)
    latex = re.sub(r"\\mbox\{\\bf\s+([^}]+)\}", r"\\mathbf{\1}", latex)

    number = extract_equation_number_near(math_el) if display else None
    return latex, display, number


def extract_equation_number_near(math_el) -> str | None:
    """Find nearby equation tags like (1.1) used by ar5iv / MathJax / Wikipedia."""
    for attr in (math_el.get("id"),):
        if not attr:
            continue
        m = re.search(r"(?:eqn|eq|equation)[-_:]?(\d+(?:\.\d+)*)", str(attr), re.I)
        if m:
            return f"({m.group(1)})"

    selectors = (
        ".ltx_tag_equation",
        ".ltx_tag.ltx_tag_equation",
        ".ltx_EqnNum",
        ".equation-number",
        ".eqno",
        "[class*='eqn-num']",
        "[class*='equation-number']",
    )
    depth = 0
    for parent in [math_el, *list(math_el.parents)]:
        if not getattr(parent, "name", None):
            continue
        depth += 1
        if depth > 8 or parent.name in {"body", "html"}:
            break
        for sel in selectors:
            try:
                nodes = parent.select(sel)
            except Exception:
                nodes = []
            for node in nodes:
                num = _normalize_eq_number(node.get_text(" ", strip=True))
                if num:
                    return num
        if parent.name in {"tr", "div", "p", "td", "span", "section", "figure"}:
            for child in list(getattr(parent, "children", [])):
                if not getattr(child, "name", None) or child is math_el:
                    continue
                txt = child.get_text(" ", strip=True) if hasattr(child, "get_text") else ""
                num = _normalize_eq_number(txt)
                if num and len(txt) <= 12:
                    return num
    return None


def _normalize_eq_number(text: str) -> str | None:
    t = (text or "").strip()
    if not t:
        return None
    m = re.fullmatch(r"\(?\s*(\d+(?:\.\d+)*)\s*\)?", t)
    if m:
        return f"({m.group(1)})"
    m = re.fullmatch(r"(?:Eq\.?|Equation)\s*\(?\s*(\d+(?:\.\d+)*)\s*\)?", t, re.I)
    if m:
        return f"({m.group(1)})"
    return None


def mathml_to_latex_approx(math_el) -> str:
    """Very small MathML→LaTeX for common constructs when annotation missing."""
    try:
        # operate on a clone-ish string parse to avoid BS namespace pain
        xml = str(math_el)
        # strip default ns for ET
        xml = re.sub(r'\sxmlns="[^"]+"', "", xml)
        root = ET.fromstring(xml)
    except Exception:
        return math_el.get_text(" ", strip=True)

    def walk(el) -> str:
        tag = _local(el.tag)
        if tag in {"math", "mrow", "mstyle", "semantics", "mpadded", "mphantom"}:
            return "".join(walk(c) for c in list(el))
        if tag == "mi":
            return (el.text or "").strip()
        if tag == "mn":
            return (el.text or "").strip()
        if tag == "mo":
            t = (el.text or "").strip()
            # spacing operators
            if t in {"=", "+", "-", "±", "·", "×", "÷", ",", ";"}:
                return f" {t} " if t not in {",", ";"} else f"{t} "
            return t
        if tag == "msup":
            kids = list(el)
            if len(kids) >= 2:
                return f"{{{walk(kids[0])}}}^{{{walk(kids[1])}}}"
            return "".join(walk(c) for c in kids)
        if tag == "msub":
            kids = list(el)
            if len(kids) >= 2:
                return f"{{{walk(kids[0])}}}_{{{walk(kids[1])}}}"
            return "".join(walk(c) for c in kids)
        if tag == "msubsup":
            kids = list(el)
            if len(kids) >= 3:
                return f"{{{walk(kids[0])}}}_{{{walk(kids[1])}}}^{{{walk(kids[2])}}}"
            return "".join(walk(c) for c in kids)
        if tag == "mfrac":
            kids = list(el)
            if len(kids) >= 2:
                return f"\\frac{{{walk(kids[0])}}}{{{walk(kids[1])}}}"
            return "".join(walk(c) for c in kids)
        if tag == "msqrt":
            return f"\\sqrt{{{''.join(walk(c) for c in list(el))}}}"
        if tag == "mroot":
            kids = list(el)
            if len(kids) >= 2:
                return f"\\sqrt[{walk(kids[1])}]{{{walk(kids[0])}}}"
            return "".join(walk(c) for c in kids)
        if tag == "mtext":
            t = (el.text or "").strip()
            return f"\\text{{{t}}}" if t else ""
        if tag in {"annotation", "annotation-xml"}:
            return ""
        return "".join(walk(c) for c in list(el)) + (el.text or "")

    return re.sub(r"\s+", " ", walk(root)).strip()


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    if ":" in tag:
        return tag.split(":", 1)[-1]
    return tag


def replace_html_math_with_placeholders(soup) -> dict[str, str]:
    """Replace <math> and script[type^=math/tex] with placeholders.

    Returns mapping placeholder -> markdown math snippet.
    """
    mapping: dict[str, str] = {}
    i = 0

    # MathML
    for math in list(soup.find_all("math")):
        latex, display, number = extract_latex_from_math_element(math)
        md = latex_to_markdown(latex, display=display)
        if not md:
            md = math.get_text(" ", strip=True)
        if number and display and md:
            md = f"{md}\n\n*{number}*"
            _remove_nearby_equation_number_nodes(math, number)
        key = f"@@MATH{i}@@"
        i += 1
        mapping[key] = md
        math.replace_with(key)

    # MathJax script tags
    for sc in list(soup.find_all("script")):
        typ = (sc.get("type") or "").lower()
        if not typ.startswith("math/tex"):
            continue
        latex = (sc.string or sc.get_text() or "").strip()
        display = "mode=display" in typ or "display" in typ
        md = latex_to_markdown(latex, display=display)
        number = extract_equation_number_near(sc) if display else None
        if number and display and md:
            md = f"{md}\n\n*{number}*"
            _remove_nearby_equation_number_nodes(sc, number)
        key = f"@@MATH{i}@@"
        i += 1
        mapping[key] = md
        sc.replace_with(key)

    return mapping


def _remove_nearby_equation_number_nodes(math_el, number: str) -> None:
    target = _normalize_eq_number(number) or number
    depth = 0
    for parent in [math_el, *list(math_el.parents)]:
        if not getattr(parent, "name", None):
            continue
        depth += 1
        if depth > 6 or parent.name in {"body", "html"}:
            break
        for node in list(parent.find_all(True)):
            if node is math_el:
                continue
            classes = " ".join(node.get("class") or [])
            if not re.search(r"(?i)(ltx_tag|eqno|eqn|equation-number)", classes) and node.name not in {
                "span",
                "td",
                "div",
            }:
                continue
            txt = node.get_text(" ", strip=True)
            if _normalize_eq_number(txt) == target and len(txt) <= 12:
                try:
                    node.decompose()
                except Exception:
                    pass
                return


def restore_math_placeholders(text: str, mapping: dict[str, str]) -> str:
    if not mapping:
        text = normalize_existing_latex_delimiters(text)
        return attach_orphan_equation_numbers(text)
    for k, v in mapping.items():
        text = text.replace(k, v)
    text = normalize_existing_latex_delimiters(text)
    return attach_orphan_equation_numbers(text)


def normalize_existing_latex_delimiters(text: str) -> str:
    """Normalize \\( \\) / \\[ \\] and tidy lone display blocks already in text."""
    # \( ... \) -> $...$
    text = re.sub(r"\\\((.+?)\\\)", lambda m: f"${m.group(1).strip()}$", text, flags=re.S)
    # \[ ... \] -> $$...$$
    text = re.sub(r"\\\[(.+?)\\\]", lambda m: f"$$\n{m.group(1).strip()}\n$$", text, flags=re.S)
    # collapse accidental spaces inside empty display fences
    text = re.sub(r"\$\$\s*\$\$", "", text)
    return text


def attach_orphan_equation_numbers(text: str) -> str:
    """Attach trailing (1.2)-style numbers left after display formulas."""

    def repl(m: re.Match[str]) -> str:
        body = m.group(1).strip("\n")
        num = m.group(2)
        if re.search(r"\n\*\(\d", body):
            return m.group(0)
        return f"$$\n{body}\n$$\n\n*{num}*"

    text = re.sub(
        r"\$\$\s*\n?(.*?)\n?\s*\$\$\s*(?:\n|\s)*(?:\||\s)*(\(\d+(?:\.\d+)*\))",
        repl,
        text,
        flags=re.S,
    )
    text = cleanup_formula_table_chrome(text)
    return text


def cleanup_formula_table_chrome(text: str) -> str:
    """Remove empty markdown table scaffolding around display formulas."""
    # unwrap indented table-wrapped formulas:
    # "   |  | $$\n...\n$$ |  |"  or "   |  | $$\n...\n$$\n\n*(1.1)* |  |"
    text = re.sub(
        r"(?ms)^[ \t]*\|(?:[ \t]*\|)*[ \t]*(\$\$[\s\S]*?\$\$(?:\s*\n\n\*\(\d+(?:\.\d+)*\)\*)?)[ \t]*(?:\|[ \t]*)+$",
        r"\1",
        text,
    )
    # formula starting inside a table cell on its own line: "   |  | $$"
    text = re.sub(r"(?m)^[ \t]*\|(?:[ \t]*\|)*[ \t]*(\$\$)\s*$", r"\1", text)
    # formula ending inside a table cell: "$$ |  |"
    text = re.sub(r"(?m)^[ \t]*(\$\$)[ \t]*(?:\|[ \t]*)+$", r"\1", text)
    # empty / separator-only table rows (allow leading indent)
    text = re.sub(r"(?m)^[ \t]*\|(?:[ \t]*\|)+\s*$", "", text)
    text = re.sub(r"(?m)^[ \t]*\|?(?:\s*:?---+:?\s*\|)+\s*:?---+:?\s*\|?\s*$", "", text)
    text = re.sub(r"(?m)^[ \t]*\|\s*---.*\|\s*$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + ("\n" if text.strip() else "")


# --- OMML (Office Math) ---

_M_NS = {
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}


def omml_element_to_latex(el) -> str:
    """Convert an lxml/omml element (or python-docx oxml) to approximate LaTeX."""
    tag = _local(el.tag)

    def children():
        return list(el)

    def text_of_r(r_el) -> str:
        parts = []
        for t in r_el.iter():
            if _local(t.tag) == "t" and t.text:
                parts.append(t.text)
        return "".join(parts)

    if tag in {"oMath", "oMathPara"}:
        return "".join(omml_element_to_latex(c) for c in children()).strip()
    if tag == "r":
        return text_of_r(el)
    if tag == "t":
        return el.text or ""
    if tag == "sSup":
        base = e = sup = ""
        for c in children():
            ct = _local(c.tag)
            if ct == "e":
                e = "".join(omml_element_to_latex(x) for x in c)
            elif ct == "sup":
                sup = "".join(omml_element_to_latex(x) for x in c)
        return f"{{{e}}}^{{{sup}}}"
    if tag == "sSub":
        e = sub = ""
        for c in children():
            ct = _local(c.tag)
            if ct == "e":
                e = "".join(omml_element_to_latex(x) for x in c)
            elif ct == "sub":
                sub = "".join(omml_element_to_latex(x) for x in c)
        return f"{{{e}}}_{{{sub}}}"
    if tag == "sSubSup":
        e = sub = sup = ""
        for c in children():
            ct = _local(c.tag)
            if ct == "e":
                e = "".join(omml_element_to_latex(x) for x in c)
            elif ct == "sub":
                sub = "".join(omml_element_to_latex(x) for x in c)
            elif ct == "sup":
                sup = "".join(omml_element_to_latex(x) for x in c)
        return f"{{{e}}}_{{{sub}}}^{{{sup}}}"
    if tag == "f":  # fraction
        num = den = ""
        for c in children():
            ct = _local(c.tag)
            if ct == "num":
                num = "".join(omml_element_to_latex(x) for x in c)
            elif ct == "den":
                den = "".join(omml_element_to_latex(x) for x in c)
        return f"\\frac{{{num}}}{{{den}}}"
    if tag == "rad":  # radical
        deg = e = ""
        for c in children():
            ct = _local(c.tag)
            if ct == "deg":
                deg = "".join(omml_element_to_latex(x) for x in c)
            elif ct == "e":
                e = "".join(omml_element_to_latex(x) for x in c)
        if deg:
            return f"\\sqrt[{deg}]{{{e}}}"
        return f"\\sqrt{{{e}}}"
    if tag == "nary":
        # integral/sum/product
        ch = sub = sup = e = ""
        for c in children():
            ct = _local(c.tag)
            if ct == "naryPr":
                for x in c:
                    if _local(x.tag) == "chr":
                        ch = (
                            x.get(qn_m("val"))
                            or x.get("{http://schemas.openxmlformats.org/officeDocument/2006/math}val")
                            or ""
                        )
            elif ct == "sub":
                sub = "".join(omml_element_to_latex(x) for x in c)
            elif ct == "sup":
                sup = "".join(omml_element_to_latex(x) for x in c)
            elif ct == "e":
                e = "".join(omml_element_to_latex(x) for x in c)
        op = {
            "∫": "\\int",
            "∬": "\\iint",
            "∭": "\\iiint",
            "∑": "\\sum",
            "∏": "\\prod",
            "⋃": "\\bigcup",
            "⋂": "\\bigcap",
        }.get(ch, ch or "\\sum")
        if sub or sup:
            return f"{op}_{{{sub}}}^{{{sup}}}{{{e}}}"
        return f"{op}{{{e}}}"
    if tag == "d":  # delimiter
        beg = end = ""
        e_parts: list[str] = []
        for c in children():
            ct = _local(c.tag)
            if ct == "dPr":
                for x in c:
                    xt = _local(x.tag)
                    if xt == "begChr":
                        beg = x.get(qn_m("val")) or x.get("{http://schemas.openxmlformats.org/officeDocument/2006/math}val") or "("
                    elif xt == "endChr":
                        end = x.get(qn_m("val")) or x.get("{http://schemas.openxmlformats.org/officeDocument/2006/math}val") or ")"
            elif ct == "e":
                e_parts.append(omml_element_to_latex(c))
        body = ",".join(e_parts) if e_parts else "".join(omml_element_to_latex(c) for c in children())
        beg = beg or "("
        end = end or ")"
        return f"\\left{beg}{body}\\right{end}"
    if tag == "m":  # matrix
        rows: list[str] = []
        for c in children():
            if _local(c.tag) != "mr":
                continue
            cells = [omml_element_to_latex(x) for x in c if _local(x.tag) == "e"]
            rows.append(" & ".join(cells))
        body = " \\\\\n".join(rows)
        return f"\\begin{{matrix}}\n{body}\n\\end{{matrix}}"
    if tag == "eqArr":
        rows = []
        for c in children():
            if _local(c.tag) == "e":
                rows.append(omml_element_to_latex(c))
        body = " \\\\\n".join(rows)
        return f"\\begin{{aligned}}\n{body}\n\\end{{aligned}}"
    if tag == "func":
        name = arg = ""
        for c in children():
            ct = _local(c.tag)
            if ct == "fName":
                name = "".join(omml_element_to_latex(x) for x in c)
            elif ct == "e":
                arg = "".join(omml_element_to_latex(x) for x in c)
        name = name.strip() or "f"
        return f"\\{name}{{{arg}}}" if re.fullmatch(r"[A-Za-z]+", name) else f"{name}({arg})"
    if tag in {"acc", "bar", "box", "borderBox", "groupChr"}:
        e = ""
        chr_ = ""
        for c in children():
            ct = _local(c.tag)
            if ct == "e":
                e = "".join(omml_element_to_latex(x) for x in c)
            elif ct.endswith("Pr"):
                for x in c:
                    if _local(x.tag) == "chr":
                        chr_ = (
                            x.get(qn_m("val"))
                            or x.get("{http://schemas.openxmlformats.org/officeDocument/2006/math}val")
                            or ""
                        )
        if tag == "bar" or chr_ in {"¯", "‾"}:
            return f"\\bar{{{e}}}"
        if chr_ in {"→", "⃗"}:
            return f"\\vec{{{e}}}"
        if chr_ in {"^", "ˆ"}:
            return f"\\hat{{{e}}}"
        if chr_ in {"~", "˜"}:
            return f"\\tilde{{{e}}}"
        return e
    if tag == "sPre":
        # left subscript/superscript
        e = sub = sup = ""
        for c in children():
            ct = _local(c.tag)
            if ct == "e":
                e = "".join(omml_element_to_latex(x) for x in c)
            elif ct == "sub":
                sub = "".join(omml_element_to_latex(x) for x in c)
            elif ct == "sup":
                sup = "".join(omml_element_to_latex(x) for x in c)
        return f"{{}}_{{{sub}}}^{{{sup}}}{e}"
    # generic container
    if tag in {"e", "num", "den", "sub", "sup", "deg", "fName", "mr"}:
        return "".join(omml_element_to_latex(c) for c in children())
    # fallback: recurse all
    parts = [omml_element_to_latex(c) for c in children()]
    if parts:
        return "".join(parts)
    return (el.text or "") if hasattr(el, "text") else ""


def qn_m(name: str) -> str:
    return f"{{http://schemas.openxmlformats.org/officeDocument/2006/math}}{name}"


_MATH_HEAVY = re.compile(
    r"[∫∑∏√∞≈≠≤≥±×÷∂∇α-ωΑ-Ω^=_/\\]"
    r"|(\bdx\b)|(\be\^)|(\bpi\b)|(\bsin\b)|(\bcos\b)|(\blog\b)"
)


def looks_like_formula_text(text: str) -> bool:
    t = text.strip()
    if len(t) < 3 or len(t) > 200:
        return False
    score = len(_MATH_HEAVY.findall(t))
    if score >= 2:
        return True
    if re.search(r".+=.+", t) and score >= 1:
        return True
    if re.search(r"[²³⁴₅₆]|\^\(|/\(", t):
        return True
    return False


def unicode_formula_to_latexish(text: str) -> str:
    """Light cleanup so unicode math reads ok inside $...$."""
    t = text.strip()
    # strip prose labels like "Energy: E = mc2"
    t = re.sub(r"^[A-Za-z][A-Za-z \-]{1,24}:\s*", "", t)
    repl = {
        "²": "^{2}",
        "³": "^{3}",
        "√": "\\sqrt",
        "∑": "\\sum",
        "∫": "\\int",
        "π": "\\pi",
        "±": "\\pm",
        "×": "\\times",
        "÷": "\\div",
        "∞": "\\infty",
        "≈": "\\approx",
        "≠": "\\neq",
        "≤": "\\leq",
        "≥": "\\geq",
        "∂": "\\partial",
        "∇": "\\nabla",
        "·": "\\cdot",
    }
    for a, b in repl.items():
        t = t.replace(a, b)
    # e^(i\pi) style already ascii
    t = re.sub(r"\s+", " ", t)
    return t.strip()
