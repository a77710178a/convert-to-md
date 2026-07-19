"""Specialized formula OCR backends.

Preferred: pix2tex (LaTeX-OCR) when installed.
Fallback: Tesseract via convert_to_md.ocr (generic text OCR).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_PIX2TEX_MODEL = None
_PIX2TEX_TRIED = False
_PIX2TEX_ERROR: str | None = None


@dataclass
class FormulaOcrResult:
    latex: str
    engine: str


class FormulaOcrUnavailableError(RuntimeError):
    pass


def available_formula_engines() -> list[str]:
    engines: list[str] = []
    if _pix2tex_importable():
        engines.append("pix2tex")
    try:
        from convert_to_md.ocr import available_engines

        if "tesseract" in available_engines():
            engines.append("tesseract")
    except Exception:
        pass
    return engines


def _pix2tex_importable() -> bool:
    try:
        import pix2tex  # noqa: F401

        return True
    except Exception:
        return False


def _get_pix2tex_model():
    """Lazy-load LatexOCR. First call may download weights (needs network)."""
    global _PIX2TEX_MODEL, _PIX2TEX_TRIED, _PIX2TEX_ERROR
    if _PIX2TEX_MODEL is not None:
        return _PIX2TEX_MODEL
    if _PIX2TEX_TRIED:
        return None
    _PIX2TEX_TRIED = True
    try:
        from pix2tex.cli import LatexOCR

        _PIX2TEX_MODEL = LatexOCR()
        _PIX2TEX_ERROR = None
        return _PIX2TEX_MODEL
    except Exception as e:  # noqa: BLE001
        _PIX2TEX_MODEL = None
        _PIX2TEX_ERROR = str(e)
        return None


def ocr_formula_pil(img, *, engine: str = "auto") -> FormulaOcrResult:
    """OCR a PIL image expected to contain a formula.

    engine: auto | pix2tex | tesseract
    """
    engine = (engine or "auto").lower().strip()
    if img.mode not in {"RGB", "L"}:
        img = img.convert("RGB")

    errors: list[str] = []

    if engine in {"auto", "pix2tex"}:
        model = _get_pix2tex_model()
        if model is not None:
            try:
                latex = (model(img) or "").strip()
                latex = _clean_pix2tex_latex(latex)
                if latex:
                    return FormulaOcrResult(latex=latex, engine="pix2tex")
                errors.append("pix2tex returned empty latex")
            except Exception as e:  # noqa: BLE001
                errors.append(f"pix2tex: {e}")
        else:
            msg = _PIX2TEX_ERROR or "package missing or model init failed"
            if engine == "pix2tex":
                raise FormulaOcrUnavailableError(
                    "pix2tex is installed but not ready "
                    f"({msg}). First run needs network to download model weights; "
                    'or install with: pip install -e ".[formula]"'
                )
            errors.append(f"pix2tex unavailable: {msg}")

    if engine in {"auto", "tesseract"}:
        try:
            from convert_to_md.mathutil import unicode_formula_to_latexish
            from convert_to_md.ocr import ocr_pil_image

            text = ocr_pil_image(img)
            if text:
                return FormulaOcrResult(
                    latex=unicode_formula_to_latexish(text),
                    engine="tesseract",
                )
            errors.append("tesseract returned empty text")
        except Exception as e:  # noqa: BLE001
            errors.append(f"tesseract: {e}")
        if engine == "tesseract":
            raise FormulaOcrUnavailableError(
                "tesseract formula OCR failed. Install Tesseract + pip install -e \".[ocr]\""
            )

    detail = "; ".join(errors) if errors else "no engine available"
    raise FormulaOcrUnavailableError(f"Formula OCR unavailable ({detail})")


def ocr_formula_bytes(data: bytes, *, engine: str = "auto") -> FormulaOcrResult:
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(data))
    return ocr_formula_pil(img, engine=engine)


def ocr_formula_path(path: Path, *, engine: str = "auto") -> FormulaOcrResult:
    from PIL import Image

    return ocr_formula_pil(Image.open(path), engine=engine)


def _clean_pix2tex_latex(tex: str) -> str:
    tex = (tex or "").strip()
    # model sometimes returns $...$ already
    if tex.startswith("$$") and tex.endswith("$$") and len(tex) > 4:
        tex = tex[2:-2].strip()
    elif tex.startswith("$") and tex.endswith("$") and len(tex) > 2:
        tex = tex[1:-1].strip()
    # common wrappers
    tex = tex.replace("\n", " ")
    while "  " in tex:
        tex = tex.replace("  ", " ")
    try:
        from convert_to_md.mathutil import postprocess_formula_latex

        tex = postprocess_formula_latex(tex)
    except Exception:
        pass
    return tex.strip()
