from __future__ import annotations

import hashlib
import json
from pathlib import Path

CACHE_VERSION = 8
CACHE_NAME = ".convert_to_md_cache.json"


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def cache_key(
    source: Path,
    *,
    converter_name: str,
    max_table_rows: int,
    pdf_max_pages: int | None,
    pdf_page_headings: bool = False,
    pdf_ocr: str = "auto",
    pdf_formula_ocr: str = "auto",
    html_keep_infobox: bool = False,
) -> str:
    payload = {
        "v": CACHE_VERSION,
        "sha256": file_sha256(source),
        "converter": converter_name,
        "max_table_rows": max_table_rows,
        "pdf_max_pages": pdf_max_pages,
        "pdf_page_headings": pdf_page_headings,
        "pdf_ocr": pdf_ocr,
        "pdf_formula_ocr": pdf_formula_ocr,
        "html_keep_infobox": html_keep_infobox,
        "source_name": source.name,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_cache(cache_path: Path) -> dict:
    if not cache_path.is_file():
        return {}
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(cache_path: Path, data: dict) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def is_fresh(output_md: Path, key: str, cache_path: Path | None = None) -> bool:
    if not output_md.is_file():
        return False
    cache_path = cache_path or (output_md.parent / CACHE_NAME)
    data = load_cache(cache_path)
    entry = data.get(str(output_md.name))
    if not entry:
        return False
    return entry.get("key") == key and Path(entry.get("output", "")).name == output_md.name


def remember(output_md: Path, source: Path, key: str, cache_path: Path | None = None) -> None:
    cache_path = cache_path or (output_md.parent / CACHE_NAME)
    data = load_cache(cache_path)
    data[output_md.name] = {
        "key": key,
        "source": str(source),
        "output": str(output_md),
    }
    save_cache(cache_path, data)
