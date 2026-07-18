from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ConvertContext:
    """Per-conversion options shared by converters and renderer."""

    source: Path
    output_md: Path
    assets_dir: Path
    overwrite: bool = True
    max_table_rows: int = 5000
    pdf_max_pages: int | None = None
    # PDF
    pdf_page_headings: bool = False
    pdf_ocr: str = "auto"  # auto | off | force  (full-page OCR for scans)
    pdf_formula_ocr: str = "auto"  # auto | off | force  (formula region / image OCR)
    formula_ocr_engine: str = "auto"  # auto | pix2tex | tesseract
    # HTML
    html_keep_infobox: bool = False
    html_keep_navboxes: bool = False
    extra: dict = field(default_factory=dict)

    def ensure_dirs(self) -> None:
        self.output_md.parent.mkdir(parents=True, exist_ok=True)
