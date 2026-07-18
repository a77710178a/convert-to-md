from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


# extension → logical kind
EXT_MAP: dict[str, str] = {
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".html": "html",
    ".htm": "html",
    ".txt": "text",
    ".md": "text",
    ".markdown": "text",
    ".csv": "csv",
    ".tsv": "tsv",
    ".json": "json",
    ".xml": "xml",
    ".epub": "epub",
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".tif": "image",
    ".tiff": "image",
    ".bmp": "image",
    ".gif": "image",
}


@dataclass(frozen=True)
class SniffResult:
    path: Path
    ext: str
    kind: str
    mime_hint: str | None = None


def sniff(path: Path) -> SniffResult:
    path = path.resolve()
    ext = path.suffix.lower()
    kind = EXT_MAP.get(ext, "unknown")

    if path.is_file():
        head = _read_head(path, 16)
        if head.startswith(b"%PDF"):
            kind = "pdf"
            ext = ".pdf"
        elif head[:2] == b"PK":
            if kind == "unknown":
                kind = _sniff_zip_kind(path) or kind
        elif head.startswith(b"<!DOC") or head.startswith(b"<html") or head.startswith(b"<HTML"):
            kind = "html"
        elif head.startswith(b"<?xml"):
            if kind == "unknown":
                kind = "xml"
        elif head.startswith(b"\x89PNG\r\n\x1a\n"):
            kind = "image"
            ext = ".png"
        elif head[:3] == b"\xff\xd8\xff":
            kind = "image"
            ext = ".jpg"
        elif head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            kind = "image"
            ext = ".webp"
        elif head[:4] in {b"II*\x00", b"MM\x00*"}:
            kind = "image"
            ext = ".tif"
        elif head[:6] in {b"GIF87a", b"GIF89a"}:
            kind = "image"
            ext = ".gif"

    return SniffResult(path=path, ext=ext, kind=kind)


def _read_head(path: Path, n: int) -> bytes:
    try:
        with path.open("rb") as f:
            return f.read(n)
    except OSError:
        return b""


def _sniff_zip_kind(path: Path) -> str | None:
    """Best-effort zip container kind via entry names."""
    try:
        import zipfile

        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
    except Exception:
        return None

    if any(n.startswith("word/") for n in names):
        return "docx"
    if any(n.startswith("ppt/") for n in names):
        return "pptx"
    if any(n.startswith("xl/") for n in names):
        return "xlsx"
    if "mimetype" in names:
        try:
            import zipfile

            with zipfile.ZipFile(path) as zf:
                mt = zf.read("mimetype").decode("utf-8", errors="ignore")
            if "epub" in mt:
                return "epub"
        except Exception:
            pass
    return None
