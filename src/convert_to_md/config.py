"""Optional project/user config for convert-to-md.

Lookup order (later overrides earlier only via explicit CLI):
1) defaults
2) nearest convert-to-md.toml / .convert-to-md.toml walking up from CWD
3) CONVERT_TO_MD_* environment variables

CLI flags always win over config.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class AppConfig:
    max_table_rows: int = 5000
    pdf_max_pages: int | None = None
    pdf_page_headings: bool = False
    pdf_ocr: str = "auto"
    pdf_formula_ocr: str = "auto"
    formula_ocr_engine: str = "auto"  # auto | pix2tex | tesseract
    html_keep_infobox: bool = False
    workers: int = 1
    use_cache: bool = True


def default_config() -> AppConfig:
    return AppConfig()


def load_config(start: Path | None = None) -> AppConfig:
    cfg = default_config()
    path = _find_config_file(start or Path.cwd())
    if path is not None:
        data = _read_toml(path)
        cfg = _merge_dict(cfg, data)
    cfg = _merge_env(cfg)
    return cfg


def _find_config_file(start: Path) -> Path | None:
    names = ("convert-to-md.toml", ".convert-to-md.toml")
    cur = start.resolve()
    for parent in [cur, *cur.parents]:
        for name in names:
            p = parent / name
            if p.is_file():
                return p
        # stop at filesystem root naturally
    return None


def _read_toml(path: Path) -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    # allow [convert-to-md] table or flat keys
    if isinstance(data.get("convert-to-md"), dict):
        return dict(data["convert-to-md"])
    if isinstance(data.get("convert_to_md"), dict):
        return dict(data["convert_to_md"])
    return dict(data)


def _merge_dict(cfg: AppConfig, data: dict) -> AppConfig:
    vals = asdict(cfg)
    mapping = {
        "max_table_rows": "max_table_rows",
        "pdf_max_pages": "pdf_max_pages",
        "pdf_page_headings": "pdf_page_headings",
        "pdf_ocr": "pdf_ocr",
        "pdf_formula_ocr": "pdf_formula_ocr",
        "formula_ocr_engine": "formula_ocr_engine",
        "html_keep_infobox": "html_keep_infobox",
        "workers": "workers",
        "use_cache": "use_cache",
        "cache": "use_cache",
    }
    for src, dst in mapping.items():
        if src in data and data[src] is not None:
            vals[dst] = data[src]
    return AppConfig(**vals)


def _merge_env(cfg: AppConfig) -> AppConfig:
    vals = asdict(cfg)

    def _bool(v: str) -> bool:
        return v.strip().lower() in {"1", "true", "yes", "on"}

    env_map = {
        "CONVERT_TO_MD_MAX_TABLE_ROWS": ("max_table_rows", int),
        "CONVERT_TO_MD_PDF_MAX_PAGES": ("pdf_max_pages", int),
        "CONVERT_TO_MD_PDF_PAGE_HEADINGS": ("pdf_page_headings", _bool),
        "CONVERT_TO_MD_PDF_OCR": ("pdf_ocr", str),
        "CONVERT_TO_MD_PDF_FORMULA_OCR": ("pdf_formula_ocr", str),
        "CONVERT_TO_MD_FORMULA_OCR_ENGINE": ("formula_ocr_engine", str),
        "CONVERT_TO_MD_HTML_KEEP_INFOBOX": ("html_keep_infobox", _bool),
        "CONVERT_TO_MD_WORKERS": ("workers", int),
        "CONVERT_TO_MD_CACHE": ("use_cache", _bool),
    }
    for env, (key, cast) in env_map.items():
        raw = os.environ.get(env)
        if raw is None or raw == "":
            continue
        try:
            vals[key] = cast(raw)
        except Exception:
            continue
    return AppConfig(**vals)
