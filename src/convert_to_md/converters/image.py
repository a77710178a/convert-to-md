from __future__ import annotations

import re
from pathlib import Path

from convert_to_md.context import ConvertContext
from convert_to_md.converters.base import BaseConverter
from convert_to_md.ir import DocumentIR


class ImageConverter(BaseConverter):
    """OCR image files (png/jpg/webp/tif) to Markdown.

    - General images: page/text OCR (Tesseract)
    - Formula-like images (name/mode hints): specialized formula OCR (pix2tex → tesseract)
    """

    name = "image"
    kinds = ("image",)

    def convert(self, path: Path, ctx: ConvertContext) -> DocumentIR:
        doc = DocumentIR(source=path, title=path.stem)
        try:
            data = path.read_bytes()
            if data:
                from convert_to_md.ir import ImageAsset

                doc.image(
                    ImageAsset(
                        data=data,
                        filename=path.name,
                        alt=path.stem,
                    )
                )
        except Exception:
            pass

        engine = getattr(ctx, "formula_ocr_engine", "auto") or "auto"
        formula_mode = (getattr(ctx, "pdf_formula_ocr", "auto") or "auto").lower()
        prefer_formula = formula_mode == "force" or _looks_formula_filename(path) or engine == "pix2tex"

        if prefer_formula and formula_mode != "off":
            formula_text = _try_formula_ocr(path, engine=engine)
            if formula_text:
                doc.metadata["formula_ocr_engine"] = formula_text[1]
                doc.formula(formula_text[0], display=True)
                return doc

        # general image OCR
        try:
            from convert_to_md.ocr import OcrUnavailableError, ocr_image

            text = ocr_image(path)
        except Exception as e:
            # last chance: formula OCR if general OCR unavailable
            formula_text = _try_formula_ocr(path, engine=engine) if formula_mode != "off" else None
            if formula_text:
                doc.metadata["formula_ocr_engine"] = formula_text[1]
                doc.formula(formula_text[0], display=True)
                return doc
            doc.paragraph(f"_{e}_")
            return doc

        text = _cleanup_ocr(text)
        if not text:
            # optional formula fallback for empty text OCR on formula-ish names
            if prefer_formula:
                formula_text = _try_formula_ocr(path, engine=engine)
                if formula_text:
                    doc.metadata["formula_ocr_engine"] = formula_text[1]
                    doc.formula(formula_text[0], display=True)
                    return doc
            doc.paragraph("_OCR produced no text._")
            return doc

        for para in re.split(r"\n\s*\n", text):
            para = " ".join(ln.strip() for ln in para.splitlines() if ln.strip())
            if para:
                doc.paragraph(para)
        return doc


def _try_formula_ocr(path: Path, *, engine: str) -> tuple[str, str] | None:
    try:
        from convert_to_md.formula_ocr import FormulaOcrUnavailableError, ocr_formula_path

        result = ocr_formula_path(path, engine=engine)
        text = _cleanup_ocr(result.latex)
        if not text:
            return None
        return text, result.engine
    except Exception:
        return None


def _cleanup_ocr(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _looks_formula_filename(path: Path) -> bool:
    name = path.stem.lower()
    return any(k in name for k in ("formula", "equation", "eq", "math", "latex"))
