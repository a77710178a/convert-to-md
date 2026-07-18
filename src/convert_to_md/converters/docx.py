from __future__ import annotations

from pathlib import Path

from convert_to_md.context import ConvertContext
from convert_to_md.converters.base import BaseConverter
from convert_to_md.ir import DocumentIR, ImageAsset
from convert_to_md.mathutil import latex_to_markdown, omml_element_to_latex


class DocxConverter(BaseConverter):
    name = "docx"
    kinds = ("docx",)

    def convert(self, path: Path, ctx: ConvertContext) -> DocumentIR:
        from docx import Document
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = Document(str(path))
        doc = DocumentIR(source=path, title=path.stem)

        try:
            if document.core_properties.title:
                doc.title = document.core_properties.title
        except Exception:
            pass

        image_i = 0
        math_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"

        def handle_paragraph(p: Paragraph) -> None:
            nonlocal image_i
            style_name = (p.style.name if p.style is not None else "") or ""

            # images
            for run in p.runs:
                for drawing in run._element.findall(".//" + qn("a:blip")):
                    embed = drawing.get(qn("r:embed"))
                    if not embed:
                        continue
                    try:
                        part = document.part.related_parts[embed]
                        blob = part.blob
                        content_type = getattr(part, "content_type", "") or ""
                        ext = _ext_from_content_type(content_type) or Path(part.partname).suffix or ".png"
                        image_i += 1
                        asset = ImageAsset(
                            data=blob,
                            filename=f"image_{image_i}{ext}",
                            alt=p.text.strip() or f"image_{image_i}",
                            content_type=content_type or None,
                        )
                        doc.image(asset)
                    except Exception:
                        continue

            # OMML equations in paragraph (block or inline)
            omaths = p._element.findall(".//" + math_ns + "oMath")
            omath_paras = p._element.findall(".//" + math_ns + "oMathPara")
            text = p.text.strip()

            if omath_paras or omaths:
                # if paragraph is mostly equation, emit formula block(s)
                pure_math = not text or len(text) < 3
                for om in omath_paras or omaths:
                    try:
                        latex = omml_element_to_latex(om)
                    except Exception:
                        latex = ""
                    if latex:
                        # oMathPara => display; lone oMath with little text => display
                        display = bool(omath_paras) or pure_math
                        if pure_math:
                            doc.formula(latex, display=display)
                        else:
                            # keep surrounding text with inline formula
                            md = latex_to_markdown(latex, display=False)
                            # if text already contains flattened unicode of formula, just append formula
                            if text and md not in text:
                                doc.paragraph(f"{text} {md}".strip())
                                text = ""  # avoid double emit
                            else:
                                doc.formula(latex, display=False)
                if text and not pure_math and not omath_paras:
                    # text already emitted with inline formula
                    return
                if pure_math:
                    return
                if text and omath_paras:
                    # leftover caption-like text
                    doc.paragraph(text)
                return

            if not text:
                return

            level = _heading_level(style_name)
            if level:
                doc.heading(text, level=level)
                return

            if "List" in style_name or "list" in style_name:
                doc.list_items([text], ordered="Number" in style_name)
                return

            doc.paragraph(text)

        def handle_table(table: Table) -> None:
            rows: list[list[str]] = []
            for row in table.rows:
                cells = []
                for cell in row.cells:
                    cells.append(cell.text.replace("\n", " ").strip())
                rows.append(cells)
            if len(rows) > ctx.max_table_rows:
                rows = rows[: ctx.max_table_rows]
            doc.table(rows)

        body = document.element.body
        for child in body.iterchildren():
            tag = child.tag
            if tag == qn("w:p"):
                handle_paragraph(Paragraph(child, document))
            elif tag == qn("w:tbl"):
                handle_table(Table(child, document))

        return doc


def _heading_level(style_name: str) -> int | None:
    name = style_name.strip()
    import re

    m = re.search(r"(?i)heading\s*(\d+)", name)
    if m:
        return max(1, min(int(m.group(1)), 6))
    m = re.search(r"标题\s*(\d+)", name)
    if m:
        return max(1, min(int(m.group(1)), 6))
    if name.lower() in {"title", "标题"}:
        return 1
    if name.lower() in {"subtitle", "副标题"}:
        return 2
    return None


def _ext_from_content_type(ct: str) -> str | None:
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/gif": ".gif",
        "image/bmp": ".bmp",
        "image/webp": ".webp",
        "image/x-emf": ".emf",
        "image/x-wmf": ".wmf",
    }
    return mapping.get((ct or "").lower())
