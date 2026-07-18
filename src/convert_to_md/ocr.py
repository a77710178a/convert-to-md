"""Optional OCR backends for scanned PDFs / images.

Default path stays rule-based. OCR is only used when:
  - ctx.pdf_ocr == "force", or
  - ctx.pdf_ocr == "auto" and digital text layer is empty/sparse,
  - or an image converter is used.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class OcrPage:
    index: int  # 0-based
    text: str


@dataclass
class OcrResult:
    pages: list[OcrPage]
    engine: str


class OcrUnavailableError(RuntimeError):
    pass


def available_engines() -> list[str]:
    engines: list[str] = []
    if _tesseract_ready():
        engines.append("tesseract")
    return engines


def _tesseract_ready() -> bool:
    try:
        import pytesseract

        # ensure binary is reachable; may raise
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        # common Windows install path
        candidates = [
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        ]
        for c in candidates:
            if c.is_file():
                try:
                    import pytesseract

                    pytesseract.pytesseract.tesseract_cmd = str(c)
                    pytesseract.get_tesseract_version()
                    return True
                except Exception:
                    continue
        return False


def _ensure_tesseract():
    import pytesseract

    try:
        pytesseract.get_tesseract_version()
        return pytesseract
    except Exception:
        for c in (
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        ):
            if c.is_file():
                pytesseract.pytesseract.tesseract_cmd = str(c)
                pytesseract.get_tesseract_version()
                return pytesseract
        raise OcrUnavailableError(
            "OCR engine not available. Install optional deps: "
            "`pip install pytesseract pillow` and install the Tesseract binary "
            "(https://github.com/tesseract-ocr/tesseract)."
        )


def ocr_pdf(path: Path, *, max_pages: int | None = None, dpi: int = 200) -> OcrResult:
    if not _tesseract_ready():
        raise OcrUnavailableError(
            "OCR engine not available. Install optional deps: "
            "`pip install pytesseract pillow` and install the Tesseract binary "
            "(https://github.com/tesseract-ocr/tesseract)."
        )
    return _ocr_pdf_tesseract(path, max_pages=max_pages, dpi=dpi)


def ocr_image(path: Path) -> str:
    if not _tesseract_ready():
        raise OcrUnavailableError(
            "OCR engine not available. Install optional deps: "
            "`pip install pytesseract pillow` and install the Tesseract binary."
        )
    from PIL import Image

    img = Image.open(path)
    return ocr_pil_image(img)


def ocr_image_bytes(data: bytes) -> str:
    if not _tesseract_ready():
        raise OcrUnavailableError(
            "OCR engine not available. Install optional deps: "
            "`pip install pytesseract pillow` and install the Tesseract binary."
        )
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(data))
    return ocr_pil_image(img)


def ocr_pil_image(img) -> str:
    """OCR a PIL image; light preprocess for formula/line art."""
    pytesseract = _ensure_tesseract()
    from PIL import Image, ImageOps

    if img.mode not in {"RGB", "L"}:
        img = img.convert("RGB")
    # upscale small formula crops for better glyph separation
    w, h = img.size
    if max(w, h) < 900:
        scale = max(2, int(900 / max(w, h)))
        img = img.resize((w * scale, h * scale), Image.Resampling.LANCZOS)
    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray)
    # prefer single text line config for formula strips; fall back to default
    configs = [
        "--psm 6",  # assume uniform block of text
        "--psm 7",  # single text line
        "--psm 4",  # single column
    ]
    best = ""
    for cfg in configs:
        try:
            text = (pytesseract.image_to_string(gray, config=cfg) or "").strip()
        except Exception:
            continue
        if len(text) > len(best):
            best = text
    if not best:
        best = (pytesseract.image_to_string(gray) or "").strip()
    return best


def _ocr_pdf_tesseract(path: Path, *, max_pages: int | None, dpi: int) -> OcrResult:
    import io

    import fitz
    from PIL import Image

    pytesseract = _ensure_tesseract()
    pdf = fitz.open(str(path))
    limit = pdf.page_count if max_pages is None else min(pdf.page_count, max_pages)
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pages: list[OcrPage] = []
    for i in range(limit):
        page = pdf.load_page(i)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        text = pytesseract.image_to_string(img) or ""
        pages.append(OcrPage(index=i, text=text.strip()))
    pdf.close()
    return OcrResult(pages=pages, engine="tesseract")
